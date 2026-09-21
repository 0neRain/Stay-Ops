import json

import httpx
import respx

from app.core.config import Settings
from app.services.answering import configured_answering_model
from app.services.embeddings import (
    EMBEDDING_DIMENSIONS,
    CachedEmbeddingProvider,
    OpenRouterEmbeddingProvider,
    configured_embedding_provider,
)


@respx.mock
async def test_openrouter_document_embedding_uses_document_input_type() -> None:
    route = respx.post("https://openrouter.ai/api/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"embedding": [0.0] * EMBEDDING_DIMENSIONS}]},
        )
    )
    provider = OpenRouterEmbeddingProvider(api_key="test-key", model="example/model")

    embedding = await provider.embed_document("Property information")

    assert len(embedding) == EMBEDDING_DIMENSIONS
    request_payload = json.loads(route.calls.last.request.content)
    assert request_payload["input_type"] == "search_document"


@respx.mock
async def test_openrouter_query_embedding_batch_uses_query_input_type() -> None:
    route = respx.post("https://openrouter.ai/api/v1/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.2] * EMBEDDING_DIMENSIONS},
                    {"index": 0, "embedding": [0.1] * EMBEDDING_DIMENSIONS},
                ]
            },
        )
    )
    provider = OpenRouterEmbeddingProvider(api_key="test-key", model="example/model")

    embeddings = await provider.embed_queries(["first", "second"])

    assert embeddings[0][0] == 0.1
    assert embeddings[1][0] == 0.2
    request_payload = json.loads(route.calls.last.request.content)
    assert request_payload["input"] == ["first", "second"]
    assert request_payload["input_type"] == "search_query"


class CountingEmbeddingProvider:
    model = "test/counting"
    dimensions = 3

    def __init__(self) -> None:
        self.query_calls = 0

    async def embed_query(self, _: str) -> list[float]:
        self.query_calls += 1
        return [0.1, 0.2, 0.3]

    async def embed_document(self, _: str) -> list[float]:
        return [0.4, 0.5, 0.6]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed_document(text) for text in texts]


async def test_cached_provider_reuses_query_embedding_for_retrieval_and_validation() -> None:
    delegate = CountingEmbeddingProvider()
    provider = CachedEmbeddingProvider(delegate)

    first = await provider.embed_query("guest message")
    second = await provider.embed_query("guest message")

    assert first == second
    assert delegate.query_calls == 1


def test_openrouter_defaults_only_require_a_shared_api_key() -> None:
    settings = Settings(app_env="test", openrouter_api_key="shared-test-key")

    answering_model = configured_answering_model(settings)
    embedding_provider = configured_embedding_provider(settings)

    assert settings.openrouter_chat_model == "openai/gpt-5-mini"
    assert settings.openrouter_embedding_model == "openai/text-embedding-3-small"
    assert answering_model is not None
    assert answering_model.model_name == "openai/gpt-5-mini"
    assert answering_model.openrouter_api_key is not None
    assert answering_model.openrouter_api_key.get_secret_value() == "shared-test-key"
    assert embedding_provider is not None
    assert embedding_provider.model == "openai/text-embedding-3-small"


def test_separate_openrouter_keys_override_the_shared_key() -> None:
    settings = Settings(
        app_env="test",
        openrouter_api_key="shared-key",
        openrouter_chat_api_key="chat-key",
        openrouter_embedding_api_key="embedding-key",
    )

    answering_model = configured_answering_model(settings)
    embedding_provider = configured_embedding_provider(settings)

    assert settings.answering_api_key == "chat-key"
    assert settings.embedding_api_key == "embedding-key"
    assert answering_model is not None
    assert answering_model.openrouter_api_key is not None
    assert answering_model.openrouter_api_key.get_secret_value() == "chat-key"
    assert embedding_provider is not None
    assert isinstance(embedding_provider, CachedEmbeddingProvider)
    assert isinstance(embedding_provider.delegate, OpenRouterEmbeddingProvider)
    assert embedding_provider.delegate.api_key == "embedding-key"
