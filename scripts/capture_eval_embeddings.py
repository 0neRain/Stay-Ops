import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.policy.risk_examples import RISK_EXAMPLES
from app.services.embeddings import OpenRouterEmbeddingProvider
from scripts.eval_embedding_snapshot import (
    DEFAULT_SNAPSHOT_PATH,
    EmbeddingInputType,
    SnapshotEmbedding,
    write_embedding_snapshot,
)
from scripts.mock_knowledge import MOCK_KNOWLEDGE
from scripts.rag_evaluation import RagEvaluationSuite, load_suite


class SnapshotCaptureSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    openrouter_api_key: str = ""
    openrouter_embedding_api_key: str | None = None
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str | None = "http://localhost:8000"
    openrouter_app_title: str | None = "StayOps AI"
    openrouter_timeout_seconds: float = 30.0

    @property
    def embedding_api_key(self) -> str:
        return self.openrouter_embedding_api_key or self.openrouter_api_key


@dataclass(frozen=True)
class SnapshotInput:
    input_type: EmbeddingInputType
    text: str
    sources: tuple[str, ...]


def collect_snapshot_inputs(suite: RagEvaluationSuite) -> list[SnapshotInput]:
    inputs: list[SnapshotInput] = []
    for document in MOCK_KNOWLEDGE:
        for index, chunk in enumerate(document.chunks):
            inputs.append(
                SnapshotInput(
                    input_type="search_document",
                    text=chunk,
                    sources=(f"knowledge:{document.title}#{index}",),
                )
            )
    for example in RISK_EXAMPLES:
        inputs.append(
            SnapshotInput(
                input_type="search_document",
                text=example.text,
                sources=(f"policy:{example.key}",),
            )
        )
    for case in suite.cases:
        inputs.append(
            SnapshotInput(
                input_type="search_query",
                text=case.query,
                sources=(f"evaluation:{case.id}",),
            )
        )

    grouped: dict[tuple[EmbeddingInputType, str], list[str]] = {}
    for snapshot_input in inputs:
        grouped.setdefault((snapshot_input.input_type, snapshot_input.text), []).extend(
            snapshot_input.sources
        )
    return [
        SnapshotInput(input_type=input_type, text=text, sources=tuple(sorted(sources)))
        for (input_type, text), sources in grouped.items()
    ]


async def capture_snapshot(
    *,
    settings: SnapshotCaptureSettings,
    suite: RagEvaluationSuite,
    output_path: Path,
    batch_size: int,
) -> int:
    if not settings.embedding_api_key:
        raise RuntimeError("OpenRouter embedding credentials are required to capture a snapshot")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    provider = OpenRouterEmbeddingProvider(
        api_key=settings.embedding_api_key,
        model=settings.openrouter_embedding_model,
        timeout_seconds=settings.openrouter_timeout_seconds,
        base_url=settings.openrouter_base_url,
        app_url=settings.openrouter_app_url,
        app_title=settings.openrouter_app_title,
    )
    inputs = collect_snapshot_inputs(suite)
    records: list[SnapshotEmbedding] = []
    for offset in range(0, len(inputs), batch_size):
        batch = inputs[offset : offset + batch_size]
        documents = [item for item in batch if item.input_type == "search_document"]
        queries = [item for item in batch if item.input_type == "search_query"]
        document_embeddings = await provider.embed_documents([item.text for item in documents])
        query_embeddings = await provider.embed_queries([item.text for item in queries])
        records.extend(
            SnapshotEmbedding(
                input_type=item.input_type,
                text=item.text,
                sources=item.sources,
                embedding=embedding,
            )
            for item, embedding in zip(documents, document_embeddings, strict=True)
        )
        records.extend(
            SnapshotEmbedding(
                input_type=item.input_type,
                text=item.text,
                sources=item.sources,
                embedding=embedding,
            )
            for item, embedding in zip(queries, query_embeddings, strict=True)
        )
    manifest = write_embedding_snapshot(
        output_path,
        model=provider.model,
        dimensions=provider.dimensions,
        dataset_version=suite.version,
        generated_at=datetime.now(timezone.utc),
        records=records,
    )
    return len(manifest.entries)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture versioned OpenRouter embeddings for deterministic RAG evaluation"
    )
    parser.add_argument("--dataset", type=Path, default=Path("evals/rag_v1.json"))
    parser.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    settings = SnapshotCaptureSettings()
    suite = load_suite(args.dataset)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    count = asyncio.run(
        capture_snapshot(
            settings=settings,
            suite=suite,
            output_path=args.output,
            batch_size=args.batch_size,
        )
    )
    print(
        f"Captured {count} embeddings for dataset {suite.version} "
        f"with {settings.openrouter_embedding_model} in {args.output}"
    )


if __name__ == "__main__":
    main()
