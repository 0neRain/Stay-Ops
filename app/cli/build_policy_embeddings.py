import argparse
import asyncio
import hashlib
import sys
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.domain import PolicyEmbedding
from app.policy.risk_examples import RISK_EXAMPLES, RiskExample
from app.services.embeddings import EMBEDDING_DIMENSIONS, OpenRouterEmbeddingProvider


class BatchEmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class PolicyIndexSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str
    openrouter_api_key: str = ""
    openrouter_embedding_api_key: str | None = None
    openrouter_embedding_model: str = "openai/text-embedding-3-small"

    @property
    def embedding_api_key(self) -> str:
        return self.openrouter_embedding_api_key or self.openrouter_api_key


@dataclass(frozen=True)
class PolicyIndexStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


def ensure_postgres_database(database_url: str) -> None:
    if make_url(database_url).get_backend_name() != "postgresql":
        raise RuntimeError("The policy embedding index requires PostgreSQL with pgvector")


async def build_policy_index(
    session: AsyncSession,
    *,
    embedding_provider: BatchEmbeddingProvider,
    examples: tuple[RiskExample, ...] = RISK_EXAMPLES,
    batch_size: int = 32,
) -> PolicyIndexStats:
    if embedding_provider.dimensions != EMBEDDING_DIMENSIONS:
        raise ValueError(f"Policy embeddings must have {EMBEDDING_DIMENSIONS} dimensions")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    keys = [example.key for example in examples]
    if len(keys) != len(set(keys)):
        raise ValueError("Policy example keys must be unique")

    existing_rows = list((await session.scalars(select(PolicyEmbedding))).all())
    existing_by_key = {row.policy_key: row for row in existing_rows}
    stale: list[tuple[RiskExample, str]] = []
    unchanged = 0
    for example in examples:
        content_sha256 = hashlib.sha256(example.text.encode()).hexdigest()
        existing = existing_by_key.get(example.key)
        if (
            existing is not None
            and existing.content_sha256 == content_sha256
            and existing.model_name == embedding_provider.model
            and existing.dimensions == embedding_provider.dimensions
        ):
            existing.category = example.category
            existing.urgency = example.urgency
            existing.example_text = example.text
            existing.is_active = True
            unchanged += 1
        else:
            stale.append((example, content_sha256))

    embeddings: list[list[float]] = []
    for offset in range(0, len(stale), batch_size):
        batch = stale[offset : offset + batch_size]
        embeddings.extend(
            await embedding_provider.embed_documents([example.text for example, _ in batch])
        )
    if len(embeddings) != len(stale):
        raise ValueError("Embedding provider returned an unexpected item count")

    inserted = 0
    updated = 0
    for (example, content_sha256), embedding in zip(stale, embeddings, strict=True):
        if len(embedding) != embedding_provider.dimensions:
            raise ValueError("Embedding provider returned an unexpected dimension")
        existing = existing_by_key.get(example.key)
        if existing is None:
            session.add(
                PolicyEmbedding(
                    policy_key=example.key,
                    category=example.category,
                    urgency=example.urgency,
                    example_text=example.text,
                    model_name=embedding_provider.model,
                    dimensions=embedding_provider.dimensions,
                    content_sha256=content_sha256,
                    embedding=embedding,
                    is_active=True,
                )
            )
            inserted += 1
        else:
            existing.category = example.category
            existing.urgency = example.urgency
            existing.example_text = example.text
            existing.model_name = embedding_provider.model
            existing.dimensions = embedding_provider.dimensions
            existing.content_sha256 = content_sha256
            existing.embedding = embedding
            existing.is_active = True
            updated += 1

    active_keys = set(keys)
    deactivated = 0
    for existing in existing_rows:
        if existing.policy_key not in active_keys and existing.is_active:
            existing.is_active = False
            deactivated += 1
    await session.flush()
    return PolicyIndexStats(
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        deactivated=deactivated,
    )


async def build(*, settings: PolicyIndexSettings, batch_size: int) -> PolicyIndexStats:
    ensure_postgres_database(settings.database_url)
    if not settings.embedding_api_key:
        raise RuntimeError("OpenRouter embedding credentials are required")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    provider = OpenRouterEmbeddingProvider(
        api_key=settings.embedding_api_key,
        model=settings.openrouter_embedding_model,
    )
    try:
        async with session_factory() as session:
            stats = await build_policy_index(
                session,
                embedding_provider=provider,
                batch_size=batch_size,
            )
            await session.commit()
            return stats
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the semantic policy embedding index")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    settings = PolicyIndexSettings()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    stats = asyncio.run(build(settings=settings, batch_size=args.batch_size))
    print(
        "Policy embedding index: "
        f"inserted={stats.inserted}, updated={stats.updated}, "
        f"unchanged={stats.unchanged}, deactivated={stats.deactivated}"
    )


if __name__ == "__main__":
    main()
