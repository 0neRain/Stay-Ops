from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services.embeddings import EmbeddingProviderError
from scripts.capture_eval_embeddings import collect_snapshot_inputs
from scripts.eval_embedding_snapshot import (
    ReplayEmbeddingProvider,
    SnapshotEmbedding,
    write_embedding_snapshot,
)
from scripts.rag_evaluation import load_suite

DATASET_PATH = Path(__file__).parents[1] / "evals" / "rag_v1.json"
SNAPSHOT_PATH = (
    Path(__file__).parents[1] / "evals" / "fixtures" / "openrouter_embeddings_v1.manifest.json"
)


def _write_fixture(tmp_path: Path) -> Path:
    manifest_path = tmp_path / "test.manifest.json"
    write_embedding_snapshot(
        manifest_path,
        model="test/model",
        dimensions=3,
        dataset_version="test-v1",
        generated_at=datetime(2026, 9, 14, tzinfo=timezone.utc),
        records=[
            SnapshotEmbedding(
                input_type="search_document",
                text="document",
                sources=("knowledge:document#0",),
                embedding=[0.1, 0.2, 0.3],
            ),
            SnapshotEmbedding(
                input_type="search_query",
                text="question",
                sources=("evaluation:question",),
                embedding=[0.4, 0.5, 0.6],
            ),
        ],
    )
    return manifest_path


async def test_snapshot_replays_document_query_and_batch_embeddings(tmp_path: Path) -> None:
    provider = ReplayEmbeddingProvider.from_manifest(_write_fixture(tmp_path))

    assert provider.source_model == "test/model"
    assert provider.model.startswith("test/model@snapshot:")
    assert provider.dimensions == 3
    assert provider.dataset_version == "test-v1"
    assert await provider.embed_document("document") == pytest.approx([0.1, 0.2, 0.3])
    assert await provider.embed_query("question") == pytest.approx([0.4, 0.5, 0.6])
    document_batch = await provider.embed_documents(["document"])
    query_batch = await provider.embed_queries(["question"])
    assert document_batch[0] == pytest.approx([0.1, 0.2, 0.3])
    assert query_batch[0] == pytest.approx([0.4, 0.5, 0.6])


async def test_snapshot_fails_closed_for_missing_or_wrong_input_type(tmp_path: Path) -> None:
    provider = ReplayEmbeddingProvider.from_manifest(_write_fixture(tmp_path))

    with pytest.raises(EmbeddingProviderError, match="refresh the snapshot"):
        await provider.embed_query("new question")
    with pytest.raises(EmbeddingProviderError, match="refresh the snapshot"):
        await provider.embed_query("document")


def test_snapshot_detects_vector_corruption(tmp_path: Path) -> None:
    manifest_path = _write_fixture(tmp_path)
    vectors_path = tmp_path / "test.f32"
    payload = bytearray(vectors_path.read_bytes())
    payload[0] ^= 0xFF
    vectors_path.write_bytes(payload)

    with pytest.raises(ValueError, match="checksum"):
        ReplayEmbeddingProvider.from_manifest(manifest_path)


def test_snapshot_inputs_cover_knowledge_policy_and_every_eval_query() -> None:
    suite = load_suite(DATASET_PATH)
    inputs = collect_snapshot_inputs(suite)
    sources = {source for snapshot_input in inputs for source in snapshot_input.sources}

    assert len(inputs) == 48
    assert sum(item.input_type == "search_document" for item in inputs) == 26
    assert sum(item.input_type == "search_query" for item in inputs) == 22
    assert "knowledge:Wi-Fi and home office#0" in sources
    assert "policy:safety-06" in sources
    assert {f"evaluation:{case.id}" for case in suite.cases} <= sources


async def test_committed_snapshot_matches_every_current_input() -> None:
    suite = load_suite(DATASET_PATH)
    provider = ReplayEmbeddingProvider.from_manifest(SNAPSHOT_PATH)

    assert provider.source_model == "openai/text-embedding-3-small"
    assert provider.model.startswith("openai/text-embedding-3-small@snapshot:")
    assert provider.dimensions == 1536
    assert provider.dataset_version == suite.version
    for snapshot_input in collect_snapshot_inputs(suite):
        if snapshot_input.input_type == "search_document":
            embedding = await provider.embed_document(snapshot_input.text)
        else:
            embedding = await provider.embed_query(snapshot_input.text)
        assert len(embedding) == provider.dimensions
