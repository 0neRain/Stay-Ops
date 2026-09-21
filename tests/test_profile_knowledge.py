from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.auth import Tenant, User
from app.models.domain import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion, Property
from app.services.knowledge import KnowledgeRetriever
from app.services.profile_knowledge import (
    PROFILE_DOCUMENT_TYPE,
    ProfileKnowledgeIndexer,
    publish_confirmed_profile,
)


class ProfileEmbeddingProvider:
    model = "test/profile-embedding"
    dimensions = 1536

    async def embed_query(self, text: str) -> list[float]:
        return [float(bool(text))] * self.dimensions

    async def embed_document(self, text: str) -> list[float]:
        return [float(bool(text))] * self.dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(bool(text))] * self.dimensions for text in texts]


async def test_changed_profile_creates_a_new_authoritative_version_and_embedding(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with db_session_factory() as session:
        tenant = Tenant(name="Profile Test", slug="profile-test")
        user = User(
            email="profile@example.com",
            full_name="Profile Owner",
            password_hash="not-used-in-this-test",
        )
        session.add_all([tenant, user])
        await session.flush()
        property_record = Property(
            tenant_id=tenant.id,
            name="Draft Home",
            timezone="UTC",
        )
        session.add(property_record)
        await session.flush()

        first = await publish_confirmed_profile(
            session,
            tenant_id=tenant.id,
            property_id=property_record.id,
            actor_user_id=user.id,
            profile={"name": "Casa Test", "timezone": "UTC", "wifi_network": "OldNetwork"},
        )
        second = await publish_confirmed_profile(
            session,
            tenant_id=tenant.id,
            property_id=property_record.id,
            actor_user_id=user.id,
            profile={
                "name": "Casa Test",
                "timezone": "Europe/Rome",
                "wifi_network": "ConfirmedNetwork",
                "parking_instructions": "Use space 7.",
            },
        )
        await session.commit()
        tenant_id = tenant.id
        property_id = property_record.id

    assert first.document_id == second.document_id
    assert first.version == 1
    assert second.version == 2
    assert second.created_version is True

    async with db_session_factory() as session:
        version_count = await session.scalar(
            select(func.count(KnowledgeVersion.id)).where(
                KnowledgeVersion.document_id == second.document_id
            )
        )
        assert version_count == 2
        document = await session.get(KnowledgeDocument, second.document_id)
        assert document is not None
        assert document.document_type == PROFILE_DOCUMENT_TYPE

        hits = await KnowledgeRetriever(session).search(
            tenant_id=tenant_id,
            property_id=property_id,
            query="What is the Wi-Fi network?",
        )
        assert hits[0].version_id == second.version_id
        assert hits[0].content == "Wi-Fi network: ConfirmedNetwork"
        assert all("OldNetwork" not in hit.content for hit in hits)

    indexer = ProfileKnowledgeIndexer(
        db_session_factory,
        embedding_provider=ProfileEmbeddingProvider(),
    )
    await indexer.process(tenant_id=tenant_id, property_id=property_id)

    async with db_session_factory() as session:
        latest_version = await session.get(KnowledgeVersion, second.version_id)
        assert latest_version is not None
        assert latest_version.embedding_status == "ready"
        chunks = list(
            (
                await session.scalars(
                    select(KnowledgeChunk).where(
                        KnowledgeChunk.version_id == second.version_id
                    )
                )
            ).all()
        )
        assert chunks
        assert all(chunk.embedding is not None for chunk in chunks)
