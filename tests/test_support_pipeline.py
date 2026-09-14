from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.domain import Escalation, KnowledgeChunk, Property
from app.models.enums import EscalationStatus
from scripts.mock_embedding_cache import MockEmbeddingCache
from scripts.mock_knowledge import MockDocument, seed_mock_knowledge
from scripts.seed_mock_knowledge import ensure_development_environment, ensure_mock_database

REGISTRATION = {
    "email": "pipeline-owner@example.com",
    "password": "correct horse battery staple",
    "full_name": "Pipeline Owner",
    "organization_name": "Pipeline Stays",
}


class FakeDocumentEmbeddingProvider:
    model = "test/embedding-model"
    dimensions = 1536

    def __init__(self) -> None:
        self.calls = 0

    async def embed_document(self, _: str) -> list[float]:
        self.calls += 1
        return [0.01] * self.dimensions


async def _register(client: httpx.AsyncClient) -> tuple[dict[str, str], UUID, UUID]:
    response = await client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 201
    body = response.json()
    tenant_id = UUID(body["active_tenant_id"])
    return {"Authorization": f"Bearer {body['access_token']}"}, tenant_id, UUID(body["user"]["id"])


async def _seed_property_and_kb(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    owner_id: UUID,
) -> UUID:
    async with session_factory() as session:
        property_record = Property(
            tenant_id=tenant_id,
            external_id="test-casa-aurora",
            name="Casa Aurora",
            timezone="Europe/Rome",
        )
        session.add(property_record)
        await session.flush()
        provider = FakeDocumentEmbeddingProvider()
        with MockEmbeddingCache(Path(":memory:")) as cache:
            stats = await seed_mock_knowledge(
                session,
                tenant_id=tenant_id,
                property_id=property_record.id,
                approved_by_id=owner_id,
                embedding_provider=provider,
                embedding_cache=cache,
            )
        assert stats.inserted_chunks == 6
        assert stats.embedded_chunks == 6
        await session.commit()
        return property_record.id


async def test_grounded_answer_contains_published_citation(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, tenant_id, owner_id = await _register(api_client)
    property_id = await _seed_property_and_kb(
        db_session_factory,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )

    response = await api_client.post(
        "/api/v1/chat/messages",
        headers=headers,
        json={"property_id": str(property_id), "content": "What is the Wi-Fi password?"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["action"] == "answered"
    assert "CasaAurora_Guest" in body["reply"]
    assert body["escalation_id"] is None
    assert body["citations"][0]["title"] == "Wi-Fi and home office"
    assert body["citations"][0]["score"] >= 0.35


async def test_unsupported_request_is_handed_off_and_can_be_claimed_and_resolved(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, tenant_id, owner_id = await _register(api_client)
    property_id = await _seed_property_and_kb(
        db_session_factory,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )

    response = await api_client.post(
        "/api/v1/chat/messages",
        headers=headers,
        json={"property_id": str(property_id), "content": "Can you arrange a helicopter?"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["action"] == "handoff"
    assert body["urgency"] == "normal"
    assert body["response_message_id"] is None
    escalation_id = body["escalation_id"]

    queue = await api_client.get("/api/v1/escalations", headers=headers)
    assert queue.status_code == 200
    assert [item["id"] for item in queue.json()] == [escalation_id]

    claimed = await api_client.post(f"/api/v1/escalations/{escalation_id}/claim", headers=headers)
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "assigned"
    assert claimed.json()["assigned_to_id"] == str(owner_id)

    resolved = await api_client.post(
        f"/api/v1/escalations/{escalation_id}/resolve",
        headers=headers,
        json={"reply": "We cannot arrange a helicopter, but we can share local taxi details."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["escalation"]["status"] == "resolved"
    assert resolved.json()["response_message_id"] is not None


async def test_refund_is_high_priority_even_when_the_kb_mentions_refunds(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, tenant_id, owner_id = await _register(api_client)
    property_id = await _seed_property_and_kb(
        db_session_factory,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    response = await api_client.post(
        "/api/v1/chat/messages",
        headers=headers,
        json={"property_id": str(property_id), "content": "I want a refund"},
    )
    assert response.status_code == 201
    assert response.json()["action"] == "handoff"
    assert response.json()["urgency"] == "high"


async def test_mock_seed_is_idempotent(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def exercise() -> tuple[int, int, int]:
        from app.models.auth import Tenant

        async with db_session_factory() as session:
            tenant = Tenant(name="Seed Test", slug="seed-test")
            session.add(tenant)
            await session.flush()
            property_record = Property(tenant_id=tenant.id, name="Seed House", timezone="UTC")
            session.add(property_record)
            await session.flush()
            provider = FakeDocumentEmbeddingProvider()
            with MockEmbeddingCache(Path(":memory:")) as cache:
                first = await seed_mock_knowledge(
                    session,
                    tenant_id=tenant.id,
                    property_id=property_record.id,
                    embedding_provider=provider,
                    embedding_cache=cache,
                )
                second = await seed_mock_knowledge(
                    session,
                    tenant_id=tenant.id,
                    property_id=property_record.id,
                    embedding_provider=provider,
                    embedding_cache=cache,
                )
            count = await session.scalar(select(func.count()).select_from(KnowledgeChunk))
            await session.commit()
            return first.inserted_chunks, second.inserted_chunks, count or 0

    first, second, count = await exercise()
    assert first == 6
    assert second == 0
    assert count == 6


async def test_mock_seed_embeds_only_new_chunks(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.models.auth import Tenant

    first_document = MockDocument(
        title="Incremental guide",
        document_type="guide",
        chunks=("Existing information.",),
    )
    updated_document = MockDocument(
        title="Incremental guide",
        document_type="guide",
        chunks=("Existing information.", "New information."),
    )
    provider = FakeDocumentEmbeddingProvider()
    async with db_session_factory() as session:
        tenant = Tenant(name="Incremental Test", slug="incremental-test")
        session.add(tenant)
        await session.flush()
        property_record = Property(tenant_id=tenant.id, name="Test House", timezone="UTC")
        session.add(property_record)
        await session.flush()
        with MockEmbeddingCache(Path(":memory:")) as cache:
            first = await seed_mock_knowledge(
                session,
                tenant_id=tenant.id,
                property_id=property_record.id,
                embedding_provider=provider,
                embedding_cache=cache,
                documents=(first_document,),
            )
            second = await seed_mock_knowledge(
                session,
                tenant_id=tenant.id,
                property_id=property_record.id,
                embedding_provider=provider,
                embedding_cache=cache,
                documents=(updated_document,),
            )
        await session.commit()

    assert first.embedded_chunks == 1
    assert second.embedded_chunks == 1
    assert second.cache_hits == 1
    assert second.inserted_chunks == 2
    assert provider.calls == 2


def test_mock_seed_is_disabled_in_production() -> None:
    from app.core.config import Settings

    settings = Settings(
        app_env="production",
        jwt_secret_key="production-only-secret-with-more-than-32-characters",
        refresh_cookie_secure=True,
    )
    with pytest.raises(RuntimeError, match="disabled in production"):
        ensure_development_environment(settings)


def test_mock_seed_rejects_non_mock_database() -> None:
    with pytest.raises(RuntimeError, match="PostgreSQL mock database"):
        ensure_mock_database("postgresql+psycopg://stayops:stayops@localhost/stayops")


async def test_escalation_record_is_persisted(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, tenant_id, owner_id = await _register(api_client)
    property_id = await _seed_property_and_kb(
        db_session_factory,
        tenant_id=tenant_id,
        owner_id=owner_id,
    )
    response = await api_client.post(
        "/api/v1/chat/messages",
        headers=headers,
        json={"property_id": str(property_id), "content": "There is a gas leak"},
    )
    assert response.status_code == 201

    async def load_escalation() -> Escalation | None:
        async with db_session_factory() as session:
            return await session.scalar(
                select(Escalation).where(Escalation.id == UUID(response.json()["escalation_id"]))
            )

    escalation = await load_escalation()
    assert escalation is not None
    assert escalation.status == EscalationStatus.OPEN
    assert escalation.urgency.value == "emergency"
