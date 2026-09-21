import hashlib
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import hash_password, issue_access_token
from app.models.auth import TenantMembership, User
from app.models.domain import KnowledgeDocument, KnowledgeVersion, Property
from app.models.enums import (
    DocumentProcessingStatus,
    KnowledgeStatus,
    MembershipRole,
)

REGISTRATION = {
    "email": "catalog-owner@example.com",
    "password": "correct horse battery staple",
    "full_name": "Catalog Owner",
    "organization_name": "Catalog Stays",
}


async def _seed_catalog(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[str, UUID, UUID, UUID]:
    registration = await api_client.post("/api/v1/auth/register", json=REGISTRATION)
    assert registration.status_code == 201
    token = registration.json()["access_token"]
    tenant_id = UUID(registration.json()["active_tenant_id"])
    async with db_session_factory() as session:
        property_record = Property(
            tenant_id=tenant_id,
            name="Casa Catalogo",
            timezone="Europe/Rome",
            address_json={"formatted": "Via Catalogo 8, Rome"},
            operational_details={
                "guest_capacity": "4",
                "house_rules": "No smoking",
                "onboarding": {
                    "status": "completed",
                    "confirmed_profile": {
                        "name": "Casa Catalogo",
                        "timezone": "Europe/Rome",
                        "address": "Via Catalogo 8, Rome",
                        "guest_capacity": "4",
                        "house_rules": "No smoking",
                    },
                },
            },
            is_active=True,
        )
        session.add(property_record)
        await session.flush()
        content = "Guests check in at 15:00.\n\nThe courtyard is shared."
        document = KnowledgeDocument(
            tenant_id=tenant_id,
            property_id=property_record.id,
            title="Guest guide",
            document_type="house_manual",
            status=KnowledgeStatus.PUBLISHED,
            processing_status=DocumentProcessingStatus.NEEDS_REVIEW,
            processing_progress=100,
            processing_stage="complete",
        )
        session.add(document)
        await session.flush()
        session.add(
            KnowledgeVersion(
                document_id=document.id,
                version=1,
                content=content,
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                embedding_status="pending",
            )
        )
        await session.commit()
        return token, tenant_id, property_record.id, document.id


async def test_catalog_lists_reads_and_updates_home_knowledge(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token, _, property_id, document_id = await _seed_catalog(
        api_client,
        db_session_factory,
    )
    headers = {"Authorization": f"Bearer {token}"}

    listing = await api_client.get("/api/v1/properties", headers=headers)
    assert listing.status_code == 200
    assert listing.json() == [
        {
            "id": str(property_id),
            "name": "Casa Catalogo",
            "address": "Via Catalogo 8, Rome",
            "property_type": None,
            "is_active": True,
            "knowledge_source_count": 1,
            "updated_at": listing.json()[0]["updated_at"],
        }
    ]

    detail_response = await api_client.get(
        f"/api/v1/properties/{property_id}",
        headers=headers,
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["can_edit"] is True
    assert detail["profile"]["guest_capacity"] == "4"
    assert detail["knowledge_sources"][0]["content"].startswith("Guests check in")
    assert detail["knowledge_sources"][0]["can_edit"] is True

    profile = {key: value or "" for key, value in detail["profile"].items()}
    profile.update(name="Casa Catalogo Updated", check_in_time="16:00")
    updated_profile = await api_client.patch(
        f"/api/v1/properties/{property_id}",
        headers=headers,
        json=profile,
    )
    assert updated_profile.status_code == 200
    assert updated_profile.json()["profile"]["name"] == "Casa Catalogo Updated"
    assert updated_profile.json()["profile"]["check_in_time"] == "16:00"

    updated_content = "Guests check in at 16:00.\n\nThe courtyard remains shared."
    source_update = await api_client.patch(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
        json={"content": updated_content},
    )
    assert source_update.status_code == 200
    assert source_update.json()["content"] == updated_content
    assert source_update.json()["version"] == 2

    async with db_session_factory() as session:
        version_count = await session.scalar(
            select(func.count(KnowledgeVersion.id)).where(
                KnowledgeVersion.document_id == document_id
            )
        )
        assert version_count == 2


async def test_viewer_can_read_catalog_but_cannot_modify_it(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, tenant_id, property_id, document_id = await _seed_catalog(
        api_client,
        db_session_factory,
    )
    async with db_session_factory() as session:
        viewer = User(
            email="catalog-viewer@example.com",
            full_name="Catalog Viewer",
            password_hash=hash_password("viewer correct horse battery staple"),
        )
        session.add(viewer)
        await session.flush()
        session.add(
            TenantMembership(
                tenant_id=tenant_id,
                user_id=viewer.id,
                role=MembershipRole.VIEWER,
            )
        )
        await session.commit()
        viewer_id = viewer.id
    settings = Settings(
        app_env="test",
        openrouter_api_key=None,
        openrouter_chat_api_key=None,
        openrouter_embedding_api_key=None,
    )
    token = issue_access_token(
        settings=settings,
        user_id=viewer_id,
        tenant_id=tenant_id,
        role=MembershipRole.VIEWER.value,
    ).encoded
    headers = {"Authorization": f"Bearer {token}"}

    listing = await api_client.get("/api/v1/properties", headers=headers)
    detail = await api_client.get(f"/api/v1/properties/{property_id}", headers=headers)

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert detail.json()["can_edit"] is False
    assert detail.json()["knowledge_sources"][0]["can_edit"] is False

    profile = {key: value or "" for key, value in detail.json()["profile"].items()}
    profile_update = await api_client.patch(
        f"/api/v1/properties/{property_id}",
        headers=headers,
        json=profile,
    )
    source_update = await api_client.patch(
        f"/api/v1/knowledge/documents/{document_id}",
        headers=headers,
        json={"content": "Viewer edit should be rejected."},
    )

    assert profile_update.status_code == 403
    assert source_update.status_code == 403
