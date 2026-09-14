import hashlib
import math
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.services.embeddings import EmbeddingProviderError

EmbeddingInputType = Literal["search_document", "search_query"]
DEFAULT_SNAPSHOT_PATH = Path("evals/fixtures/openrouter_embeddings_v1.manifest.json")
FLOAT32_BYTES = 4


@dataclass(frozen=True)
class SnapshotEmbedding:
    input_type: EmbeddingInputType
    text: str
    sources: tuple[str, ...]
    embedding: list[float]


class SnapshotEntry(BaseModel):
    key: str = Field(pattern=r"^[a-f0-9]{64}$")
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_type: EmbeddingInputType
    sources: list[str] = Field(min_length=1)
    offset_bytes: int = Field(ge=0)


class EmbeddingSnapshotManifest(BaseModel):
    format_version: Literal[1] = 1
    provider: Literal["openrouter"] = "openrouter"
    model: str = Field(min_length=1)
    dimensions: int = Field(gt=0)
    dataset_version: str = Field(min_length=1)
    generated_at: datetime
    vectors_file: str = Field(min_length=1)
    vectors_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    entries: list[SnapshotEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entries(self) -> "EmbeddingSnapshotManifest":
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Embedding snapshot keys must be unique")
        offsets = [entry.offset_bytes for entry in self.entries]
        if len(offsets) != len(set(offsets)):
            raise ValueError("Embedding snapshot offsets must be unique")
        entries = self.entries
        expected_offsets = [
            index * self.dimensions * FLOAT32_BYTES for index in range(len(entries))
        ]
        if sorted(offsets) != expected_offsets:
            raise ValueError(
                f"Embedding snapshot offsets must be contiguous for {len(entries)} vectors"
            )
        if Path(self.vectors_file).name != self.vectors_file:
            raise ValueError("Embedding vectors file must be a filename without directories")
        return self


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_key(
    *,
    model: str,
    dimensions: int,
    input_type: EmbeddingInputType,
    text: str,
) -> str:
    identity = f"{model}\0{dimensions}\0{input_type}\0{text}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _vectors_filename(manifest_path: Path) -> str:
    suffix = ".manifest.json"
    if manifest_path.name.endswith(suffix):
        return f"{manifest_path.name.removesuffix(suffix)}.f32"
    return f"{manifest_path.stem}.f32"


def write_embedding_snapshot(
    manifest_path: Path,
    *,
    model: str,
    dimensions: int,
    dataset_version: str,
    generated_at: datetime,
    records: list[SnapshotEmbedding],
) -> EmbeddingSnapshotManifest:
    if generated_at.tzinfo is None:
        raise ValueError("Embedding snapshot timestamp must include a timezone")
    if not records:
        raise ValueError("Embedding snapshot must contain at least one vector")

    ordered_records = sorted(
        records,
        key=lambda record: (record.input_type, record.sources, text_sha256(record.text)),
    )
    payload_parts: list[bytes] = []
    entries: list[SnapshotEntry] = []
    seen_keys: set[str] = set()
    for index, record in enumerate(ordered_records):
        if len(record.embedding) != dimensions:
            raise ValueError(
                f"Embedding for {record.sources!r} has {len(record.embedding)} dimensions; "
                f"expected {dimensions}"
            )
        if not all(math.isfinite(value) for value in record.embedding):
            raise ValueError(f"Embedding for {record.sources!r} contains a non-finite value")
        key = snapshot_key(
            model=model,
            dimensions=dimensions,
            input_type=record.input_type,
            text=record.text,
        )
        if key in seen_keys:
            raise ValueError(f"Duplicate embedding snapshot input for {record.sources!r}")
        seen_keys.add(key)
        payload_parts.append(struct.pack(f"<{dimensions}f", *record.embedding))
        entries.append(
            SnapshotEntry(
                key=key,
                text_sha256=text_sha256(record.text),
                input_type=record.input_type,
                sources=list(record.sources),
                offset_bytes=index * dimensions * FLOAT32_BYTES,
            )
        )

    payload = b"".join(payload_parts)
    vectors_file = _vectors_filename(manifest_path)
    manifest = EmbeddingSnapshotManifest(
        model=model,
        dimensions=dimensions,
        dataset_version=dataset_version,
        generated_at=generated_at,
        vectors_file=vectors_file,
        vectors_sha256=hashlib.sha256(payload).hexdigest(),
        entries=entries,
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    vectors_path = manifest_path.parent / vectors_file
    vectors_temporary_path = vectors_path.with_name(f".{vectors_path.name}.tmp")
    manifest_temporary_path = manifest_path.with_name(f".{manifest_path.name}.tmp")
    vectors_temporary_path.write_bytes(payload)
    manifest_temporary_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    vectors_temporary_path.replace(vectors_path)
    manifest_temporary_path.replace(manifest_path)
    return manifest


class ReplayEmbeddingProvider:
    def __init__(
        self,
        *,
        manifest: EmbeddingSnapshotManifest,
        payload: bytes,
    ) -> None:
        expected_size = len(manifest.entries) * manifest.dimensions * FLOAT32_BYTES
        if len(payload) != expected_size:
            raise ValueError(
                f"Embedding snapshot has {len(payload)} vector bytes; expected {expected_size}"
            )
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        if payload_sha256 != manifest.vectors_sha256:
            raise ValueError("Embedding snapshot vector checksum does not match the manifest")
        self._manifest = manifest
        self._payload = payload
        self._entries = {entry.key: entry for entry in manifest.entries}

    @classmethod
    def from_manifest(cls, path: Path) -> "ReplayEmbeddingProvider":
        manifest = EmbeddingSnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))
        payload = (path.parent / manifest.vectors_file).read_bytes()
        return cls(manifest=manifest, payload=payload)

    @property
    def model(self) -> str:
        return f"{self._manifest.model}@snapshot:{self._manifest.vectors_sha256[:12]}"

    @property
    def source_model(self) -> str:
        return self._manifest.model

    @property
    def dimensions(self) -> int:
        return self._manifest.dimensions

    @property
    def dataset_version(self) -> str:
        return self._manifest.dataset_version

    def _embedding(self, text: str, *, input_type: EmbeddingInputType) -> list[float]:
        key = snapshot_key(
            model=self.source_model,
            dimensions=self.dimensions,
            input_type=input_type,
            text=text,
        )
        entry = self._entries.get(key)
        if entry is None:
            raise EmbeddingProviderError(
                f"Embedding snapshot is missing {input_type} input {text_sha256(text)}; "
                "refresh the snapshot"
            )
        return list(
            struct.unpack_from(
                f"<{self.dimensions}f",
                self._payload,
                entry.offset_bytes,
            )
        )

    async def embed_query(self, text: str) -> list[float]:
        return self._embedding(text, input_type="search_query")

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_query(text) for text in texts]

    async def embed_document(self, text: str) -> list[float]:
        return self._embedding(text, input_type="search_document")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_document(text) for text in texts]
