from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.knowledge import get_document_job_queue
from app.core.config import Settings, get_settings
from app.main import app
from app.models.domain import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion, Property
from app.models.enums import DocumentProcessingStatus, KnowledgeStatus
from app.services.document_ingestion import InProcessDocumentQueue

REGISTRATION = {
    "email": "document-owner@example.com",
    "password": "correct horse battery staple",
    "full_name": "Document Owner",
    "organization_name": "Document Stays",
}


async def _register(api_client: httpx.AsyncClient) -> tuple[str, UUID]:
    response = await api_client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 201
    body = response.json()
    return body["access_token"], UUID(body["active_tenant_id"])


async def test_upload_processes_text_into_reviewable_chunks(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        document_storage_root=tmp_path / "uploads",
        document_chunk_characters=400,
        document_chunk_overlap=50,
        openrouter_api_key=None,
        openrouter_chat_api_key=None,
        openrouter_embedding_api_key=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_document_job_queue] = lambda: InProcessDocumentQueue(
        db_session_factory,
        settings=settings,
        embedding_provider=None,
    )
    token, tenant_id = await _register(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    async with db_session_factory() as session:
        property_record = Property(
            tenant_id=tenant_id,
            name="Lake House",
            timezone="Europe/Rome",
        )
        session.add(property_record)
        await session.commit()
        property_id = property_record.id

    manual = "\n".join(
        f"House instruction {index}: follow the documented step carefully." for index in range(30)
    )
    response = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data={
            "title": "Lake House manual",
            "document_type": "house_manual",
            "property_id": str(property_id),
        },
        files={"file": ("house-manual.md", manual.encode(), "text/markdown")},
    )

    assert response.status_code == 202
    uploaded = response.json()
    assert uploaded["status"] == "draft"
    assert uploaded["processing_status"] == "uploaded"
    assert uploaded["original_filename"] == "house-manual.md"
    assert "storage_key" not in uploaded

    status_response = await api_client.get(
        f"/api/v1/knowledge/documents/{uploaded['id']}", headers=headers
    )
    assert status_response.status_code == 200
    processed = status_response.json()
    assert processed["status"] == "pending_review"
    assert processed["processing_status"] == "needs_review"
    assert processed["chunk_count"] > 1
    assert processed["extracted_characters"] == len(manual)
    assert processed["embedding_status"] == "pending"
    assert processed["processing_error"] is None

    async with db_session_factory() as session:
        document = await session.get(KnowledgeDocument, UUID(uploaded["id"]))
        assert document is not None
        assert document.tenant_id == tenant_id
        assert document.storage_key is not None
        stored_path = settings.document_storage_root.joinpath(*document.storage_key.split("/"))
        assert stored_path.read_text(encoding="utf-8") == manual

        version = await session.scalar(
            select(KnowledgeVersion).where(KnowledgeVersion.document_id == document.id)
        )
        assert version is not None
        assert version.approved_at is None
        chunks = list(
            (
                await session.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.version_id == version.id)
                    .order_by(KnowledgeChunk.chunk_index)
                )
            ).all()
        )
        assert len(chunks) == processed["chunk_count"]
        assert all(chunk.embedding is None for chunk in chunks)


async def test_upload_rejects_unsupported_and_mismatched_files(
    api_client: httpx.AsyncClient,
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        document_storage_root=tmp_path / "uploads",
        document_max_upload_bytes=1024,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    token, _ = await _register(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    data = {"title": "Unsafe", "document_type": "other"}

    unsupported = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data=data,
        files={"file": ("payload.exe", b"not executable", "application/octet-stream")},
    )
    mismatched = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data=data,
        files={"file": ("manual.pdf", b"plain text", "application/pdf")},
    )
    oversized = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data=data,
        files={"file": ("manual.txt", b"x" * 1025, "text/plain")},
    )

    assert unsupported.status_code == 415
    assert mismatched.status_code == 400
    assert oversized.status_code == 413


async def test_processing_failure_is_visible_but_not_published(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = Settings(app_env="test", document_storage_root=tmp_path / "uploads")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_document_job_queue] = lambda: InProcessDocumentQueue(
        db_session_factory,
        settings=settings,
        embedding_provider=None,
    )
    token, _ = await _register(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    response = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data={"title": "Blank manual", "document_type": "house_manual"},
        files={"file": ("blank.txt", b" \n\t\n ", "text/plain")},
    )
    assert response.status_code == 202

    document_response = await api_client.get(
        f"/api/v1/knowledge/documents/{response.json()['id']}", headers=headers
    )
    body = document_response.json()
    assert body["status"] == KnowledgeStatus.DRAFT.value
    assert body["processing_status"] == DocumentProcessingStatus.FAILED.value
    assert body["processing_error"] == "No readable text was found in the document"
    assert body["chunk_count"] == 0


async def test_document_and_property_access_are_tenant_isolated(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = Settings(app_env="test", document_storage_root=tmp_path / "uploads")
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_document_job_queue] = lambda: InProcessDocumentQueue(
        db_session_factory,
        settings=settings,
        embedding_provider=None,
    )
    first_token, first_tenant_id = await _register(api_client)
    async with db_session_factory() as session:
        property_record = Property(
            tenant_id=first_tenant_id,
            name="Private Villa",
            timezone="Europe/Rome",
        )
        session.add(property_record)
        await session.commit()
        property_id = property_record.id

    first_upload = await api_client.post(
        "/api/v1/knowledge/documents",
        headers={"Authorization": f"Bearer {first_token}"},
        data={"title": "Private manual", "document_type": "house_manual"},
        files={"file": ("manual.txt", b"Private house instructions", "text/plain")},
    )
    assert first_upload.status_code == 202

    second_registration = dict(REGISTRATION)
    second_registration.update(
        email="other-owner@example.com",
        organization_name="Other Stays",
    )
    second_response = await api_client.post("/api/v1/auth/register", json=second_registration)
    assert second_response.status_code == 201
    second_token = second_response.json()["access_token"]
    second_headers = {"Authorization": f"Bearer {second_token}"}

    hidden_document = await api_client.get(
        f"/api/v1/knowledge/documents/{first_upload.json()['id']}",
        headers=second_headers,
    )
    cross_tenant_property = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=second_headers,
        data={
            "title": "Cross-tenant upload",
            "document_type": "house_manual",
            "property_id": str(property_id),
        },
        files={"file": ("manual.txt", b"Attempted upload", "text/plain")},
    )

    assert hidden_document.status_code == 404
    assert cross_tenant_property.status_code == 404
