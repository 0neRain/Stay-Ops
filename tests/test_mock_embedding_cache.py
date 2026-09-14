from pathlib import Path

import pytest

from scripts.mock_embedding_cache import MockEmbeddingCache


def test_mock_embedding_cache_persists_between_processes(tmp_path: Path) -> None:
    cache_path = tmp_path / "mock-embeddings.sqlite3"
    embedding = [0.25, -0.5, 0.75]
    with MockEmbeddingCache(cache_path) as cache:
        cache.put(
            content_sha256="content-hash",
            provider="openrouter",
            model="example/model-v1",
            dimensions=3,
            embedding=embedding,
        )

    with MockEmbeddingCache(cache_path) as cache:
        cached = cache.get(
            content_sha256="content-hash",
            provider="openrouter",
            model="example/model-v1",
            dimensions=3,
        )
    assert cached == pytest.approx(embedding)


def test_mock_embedding_cache_isolated_by_model(tmp_path: Path) -> None:
    with MockEmbeddingCache(tmp_path / "mock-embeddings.sqlite3") as cache:
        cache.put(
            content_sha256="content-hash",
            provider="openrouter",
            model="example/model-v1",
            dimensions=2,
            embedding=[0.1, 0.2],
        )
        assert (
            cache.get(
                content_sha256="content-hash",
                provider="openrouter",
                model="example/model-v2",
                dimensions=2,
            )
            is None
        )
