import sqlite3
import struct
from pathlib import Path


class MockEmbeddingCache:
    """Development-only, content-addressed cache for paid embedding results."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                content_sha256 TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                dimensions INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                PRIMARY KEY (content_sha256, provider, model, dimensions)
            )
            """
        )
        self._connection.commit()

    def get(
        self,
        *,
        content_sha256: str,
        provider: str,
        model: str,
        dimensions: int,
    ) -> list[float] | None:
        row = self._connection.execute(
            """
            SELECT embedding
            FROM embeddings
            WHERE content_sha256 = ? AND provider = ? AND model = ? AND dimensions = ?
            """,
            (content_sha256, provider, model, dimensions),
        ).fetchone()
        if row is None:
            return None
        return list(struct.unpack(f"<{dimensions}f", row[0]))

    def put(
        self,
        *,
        content_sha256: str,
        provider: str,
        model: str,
        dimensions: int,
        embedding: list[float],
    ) -> None:
        if len(embedding) != dimensions:
            raise ValueError("Embedding dimension does not match the cache key")
        payload = struct.pack(f"<{dimensions}f", *embedding)
        self._connection.execute(
            """
            INSERT OR REPLACE INTO embeddings (
                content_sha256, provider, model, dimensions, embedding
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (content_sha256, provider, model, dimensions, payload),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MockEmbeddingCache":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
