from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.core.config import Settings

EMBEDDING_DIMENSIONS = 1536


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_document(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingProviderError(Exception):
    pass


@dataclass(frozen=True)
class OpenRouterEmbeddingProvider:
    api_key: str
    model: str
    dimensions: int = EMBEDDING_DIMENSIONS
    timeout_seconds: float = 15.0
    base_url: str = "https://openrouter.ai/api/v1"
    app_url: str | None = None
    app_title: str | None = "StayOps AI"

    async def _embed_many(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        if not texts:
            return []
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                if self.app_url:
                    headers["HTTP-Referer"] = self.app_url
                if self.app_title:
                    headers["X-Title"] = self.app_title
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/embeddings",
                    headers=headers,
                    json={
                        "input": texts,
                        "model": self.model,
                        "dimensions": self.dimensions,
                        "encoding_format": "float",
                        "input_type": input_type,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                rows = sorted(payload["data"], key=lambda row: row.get("index", 0))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError("Embedding request failed") from exc
        if len(rows) != len(texts):
            raise EmbeddingProviderError("Embedding response has an unexpected item count")
        result: list[list[float]] = []
        for row in rows:
            embedding = row.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != self.dimensions:
                raise EmbeddingProviderError("Embedding response has an unexpected dimension")
            result.append([float(value) for value in embedding])
        return result

    async def _embed(self, text: str, *, input_type: str) -> list[float]:
        return (await self._embed_many([text], input_type=input_type))[0]

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed(text, input_type="search_query")

    async def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_many(texts, input_type="search_query")

    async def embed_document(self, text: str) -> list[float]:
        return await self._embed(text, input_type="search_document")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_many(texts, input_type="search_document")


@dataclass
class CachedEmbeddingProvider:
    delegate: EmbeddingProvider
    _query_cache: dict[str, list[float]] = field(default_factory=dict)

    @property
    def model(self) -> str:
        return self.delegate.model

    @property
    def dimensions(self) -> int:
        return self.delegate.dimensions

    async def embed_query(self, text: str) -> list[float]:
        if text not in self._query_cache:
            self._query_cache[text] = await self.delegate.embed_query(text)
        return self._query_cache[text]

    async def embed_document(self, text: str) -> list[float]:
        return await self.delegate.embed_document(text)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.delegate.embed_documents(texts)


def configured_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    if not settings.embedding_api_key:
        return None
    return CachedEmbeddingProvider(
        OpenRouterEmbeddingProvider(
            api_key=settings.embedding_api_key,
            model=settings.openrouter_embedding_model,
            timeout_seconds=settings.openrouter_timeout_seconds,
            base_url=settings.openrouter_base_url,
            app_url=settings.openrouter_app_url,
            app_title=settings.openrouter_app_title,
        )
    )
