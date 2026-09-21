import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password, normalize_email, verify_password
from app.models.auth import Tenant, TenantMembership, User
from app.models.domain import Property
from app.models.enums import MembershipRole
from app.services.embeddings import OpenRouterEmbeddingProvider
from scripts.mock_embedding_cache import MockEmbeddingCache
from scripts.mock_knowledge import MockSeedStats, seed_mock_knowledge

MOCK_ACCOUNT_EMAIL = "test@admin.com"
MOCK_ACCOUNT_PASSWORD = "adminadmin0000"
MOCK_ACCOUNT_NAME = "Mock Administrator"


class EnvironmentSettings(Protocol):
    @property
    def app_env(self) -> str: ...


class MockSeedSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    mock_database_url: str
    openrouter_api_key: str = ""
    openrouter_embedding_api_key: str | None = None
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    semantic_risk_threshold: float = Field(default=0.80, ge=0, le=1)
    mock_embedding_cache_path: Path = Path(".cache/mock_embeddings.sqlite3")

    @property
    def embedding_api_key(self) -> str:
        return self.openrouter_embedding_api_key or self.openrouter_api_key


@dataclass(frozen=True)
class SeedResult:
    tenant_id: UUID
    property_id: UUID
    user_id: UUID
    stats: MockSeedStats


def ensure_development_environment(settings: EnvironmentSettings) -> None:
    if settings.app_env == "production":
        raise RuntimeError("Mock knowledge seeding is disabled in production")


def ensure_mock_database(database_url: str) -> None:
    url = make_url(database_url)
    database_name = url.database or ""
    if url.get_backend_name() != "postgresql" or "mock" not in database_name.casefold():
        raise RuntimeError("MOCK_DATABASE_URL must point to a PostgreSQL mock database")


async def get_or_create_mock_scope(
    session: AsyncSession,
    *,
    tenant_slug: str,
    property_external_id: str,
) -> tuple[Tenant, Property]:
    tenant = await session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if tenant is None:
        tenant = Tenant(name="Demo Stays", slug=tenant_slug)
        session.add(tenant)
        await session.flush()

    property_record = await session.scalar(
        select(Property).where(
            Property.tenant_id == tenant.id,
            Property.external_id == property_external_id,
        )
    )
    if property_record is None:
        property_record = Property(
            tenant_id=tenant.id,
            external_id=property_external_id,
            name="Casa Aurora",
            timezone="Europe/Rome",
            address_json={"city": "Florence", "country": "IT"},
            operational_details={"mock": True},
        )
        session.add(property_record)
        await session.flush()
    return tenant, property_record


async def get_or_create_mock_account(
    session: AsyncSession,
    *,
    tenant_id: UUID,
) -> tuple[User, TenantMembership]:
    """Make the dedicated mock owner the only active account for the demo tenant."""
    email = normalize_email(MOCK_ACCOUNT_EMAIL)
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            full_name=MOCK_ACCOUNT_NAME,
            password_hash=hash_password(MOCK_ACCOUNT_PASSWORD),
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        await session.flush()
    else:
        user.full_name = MOCK_ACCOUNT_NAME
        user.is_active = True
        user.is_verified = True
        if not verify_password(MOCK_ACCOUNT_PASSWORD, user.password_hash):
            user.password_hash = hash_password(MOCK_ACCOUNT_PASSWORD)

    memberships = list(
        (
            await session.scalars(
                select(TenantMembership).where(
                    (TenantMembership.tenant_id == tenant_id)
                    | (TenantMembership.user_id == user.id)
                )
            )
        ).all()
    )
    membership = next(
        (
            item
            for item in memberships
            if item.tenant_id == tenant_id and item.user_id == user.id
        ),
        None,
    )
    if membership is None:
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=MembershipRole.OWNER,
        )
        session.add(membership)
    membership.role = MembershipRole.OWNER
    membership.is_active = True

    for item in memberships:
        if item.id == membership.id:
            continue
        if item.tenant_id == tenant_id or item.user_id == user.id:
            item.is_active = False

    await session.flush()
    return user, membership


async def seed(
    *,
    settings: MockSeedSettings,
    tenant_slug: str,
    property_external_id: str,
) -> SeedResult:
    ensure_development_environment(settings)
    ensure_mock_database(settings.mock_database_url)
    if not settings.embedding_api_key:
        raise RuntimeError("OpenRouter embedding credentials are required for mock seeding")

    engine = create_async_engine(settings.mock_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    embedding_provider = OpenRouterEmbeddingProvider(
        api_key=settings.embedding_api_key,
        model=settings.openrouter_embedding_model,
    )
    try:
        with MockEmbeddingCache(settings.mock_embedding_cache_path) as embedding_cache:
            async with session_factory() as session:
                tenant, property_record = await get_or_create_mock_scope(
                    session,
                    tenant_slug=tenant_slug,
                    property_external_id=property_external_id,
                )
                user, _ = await get_or_create_mock_account(
                    session,
                    tenant_id=tenant.id,
                )
                stats = await seed_mock_knowledge(
                    session,
                    tenant_id=tenant.id,
                    property_id=property_record.id,
                    embedding_provider=embedding_provider,
                    embedding_cache=embedding_cache,
                    approved_by_id=user.id,
                )
                await session.commit()
                return SeedResult(
                    tenant_id=tenant.id,
                    property_id=property_record.id,
                    user_id=user.id,
                    stats=stats,
                )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a development-only mock knowledge base")
    parser.add_argument("--tenant", default="demo-stays")
    parser.add_argument("--property-external-id", default="demo-casa-aurora")
    args = parser.parse_args()
    settings = MockSeedSettings()
    ensure_development_environment(settings)
    ensure_mock_database(settings.mock_database_url)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    result = asyncio.run(
        seed(
            settings=settings,
            tenant_slug=args.tenant,
            property_external_id=args.property_external_id,
        )
    )
    print(
        f"Mock KB tenant={result.tenant_id} property={result.property_id} "
        f"account={MOCK_ACCOUNT_EMAIL}: "
        f"inserted={result.stats.inserted_chunks}, embedded={result.stats.embedded_chunks}, "
        f"cache_hits={result.stats.cache_hits}, "
        f"unchanged_documents={result.stats.unchanged_documents}"
    )


if __name__ == "__main__":
    main()
