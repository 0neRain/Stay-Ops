from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import func, select

from app.api.dependencies import AppSettings, AuthContext, DatabaseSession, require_roles
from app.db.session import AsyncSessionFactory
from app.models.domain import (
    AuditEvent,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeVersion,
    Property,
)
from app.models.enums import (
    DocumentProcessingStatus,
    KnowledgeStatus,
    MembershipRole,
)
from app.schemas.knowledge import DocumentContentUpdate, DocumentResponse
from app.schemas.properties import PropertyKnowledgeSourceResponse
from app.services.document_ingestion import (
    SUPPORTED_DOCUMENT_TYPES,
    DocumentJobQueue,
    DocumentUploadError,
    InProcessDocumentQueue,
    remove_stored_upload,
    store_upload,
)
from app.services.embeddings import configured_embedding_provider
from app.services.property_catalog import (
    PropertyCatalogConflictError,
    PropertyCatalogNotFoundError,
    PropertyCatalogService,
)
from app.services.property_onboarding import can_attach_documents

router = APIRouter(prefix="/knowledge", tags=["knowledge base"])
KnowledgeEditor = Annotated[
    AuthContext,
    Depends(require_roles(MembershipRole.OWNER, MembershipRole.MANAGER)),
]


def get_document_job_queue(settings: AppSettings) -> DocumentJobQueue:
    return InProcessDocumentQueue(
        AsyncSessionFactory,
        settings=settings,
        embedding_provider=configured_embedding_provider(settings),
    )


DocumentQueue = Annotated[DocumentJobQueue, Depends(get_document_job_queue)]


async def _document_response(
    document: KnowledgeDocument, session: DatabaseSession
) -> DocumentResponse:
    version = (
        await session.execute(
            select(KnowledgeVersion)
            .where(KnowledgeVersion.document_id == document.id)
            .order_by(KnowledgeVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    chunk_count = 0
    if version is not None:
        chunk_count = (
            await session.scalar(
                select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.version_id == version.id)
            )
            or 0
        )
    eta_seconds = document.processing_eta_seconds
    if eta_seconds is not None and document.processing_status in {
        DocumentProcessingStatus.UPLOADED,
        DocumentProcessingStatus.PROCESSING,
    }:
        updated_at = document.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        eta_seconds = max(0, eta_seconds - int((now - updated_at).total_seconds()))
    return DocumentResponse(
        id=document.id,
        property_id=document.property_id,
        title=document.title,
        document_type=document.document_type,
        status=document.status,
        processing_status=document.processing_status,
        processing_progress=document.processing_progress,
        processing_stage=document.processing_stage,
        processing_eta_seconds=eta_seconds,
        original_filename=document.original_filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        file_sha256=document.file_sha256,
        processed_at=document.processed_at,
        processing_error=document.processing_error,
        created_at=document.created_at,
        extracted_characters=len(version.content) if version else None,
        chunk_count=chunk_count,
        embedding_status=version.embedding_status if version else None,
    )


@router.post(
    "/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    background_tasks: BackgroundTasks,
    context: KnowledgeEditor,
    session: DatabaseSession,
    settings: AppSettings,
    queue: DocumentQueue,
    file: Annotated[UploadFile, File(description="UTF-8 text, Markdown, HTML, PDF, or DOCX")],
    title: Annotated[str, Form(min_length=1, max_length=240)],
    document_type: Annotated[str, Form(min_length=1, max_length=80)],
    property_id: Annotated[UUID | None, Form()] = None,
) -> DocumentResponse:
    normalized_title = title.strip()
    if not normalized_title:
        raise HTTPException(status_code=422, detail="Document title cannot be blank")
    normalized_type = document_type.strip().casefold()
    if normalized_type not in SUPPORTED_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported document type: {normalized_type}",
        )
    if property_id is not None:
        property_record = await session.scalar(
            select(Property).where(
                Property.id == property_id,
                Property.tenant_id == context.tenant.id,
            )
        )
        if property_record is None or not can_attach_documents(property_record):
            raise HTTPException(status_code=404, detail="Property not found")

    document = KnowledgeDocument(
        tenant_id=context.tenant.id,
        property_id=property_id,
        title=normalized_title,
        document_type=normalized_type,
        status=KnowledgeStatus.DRAFT,
        processing_status=DocumentProcessingStatus.UPLOADED,
        processing_progress=0,
        processing_stage="queued",
        processing_eta_seconds=20,
        uploaded_by_id=context.user.id,
    )
    session.add(document)
    await session.flush()

    stored = None
    try:
        stored = await store_upload(
            file,
            tenant_id=context.tenant.id,
            document_id=document.id,
            settings=settings,
        )
        document.original_filename = stored.original_filename
        document.storage_key = stored.storage_key
        document.media_type = stored.media_type
        document.size_bytes = stored.size_bytes
        document.file_sha256 = stored.file_sha256
        session.add(
            AuditEvent(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                event_type="document.uploaded",
                entity_type="knowledge_document",
                entity_id=document.id,
                details={
                    "document_type": normalized_type,
                    "media_type": stored.media_type,
                    "size_bytes": stored.size_bytes,
                    "property_id": str(property_id) if property_id else None,
                },
            )
        )
        await session.commit()
    except DocumentUploadError as exc:
        await session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        await session.rollback()
        if stored is not None:
            await remove_stored_upload(settings.document_storage_root, stored.storage_key)
        raise HTTPException(status_code=500, detail="The document could not be uploaded") from exc
    finally:
        await file.close()

    await session.refresh(document)
    response = await _document_response(document, session)
    background_tasks.add_task(queue.process, document.id)
    return response


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    context: KnowledgeEditor,
    session: DatabaseSession,
) -> DocumentResponse:
    document = await session.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.tenant_id == context.tenant.id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _document_response(document, session)


@router.patch(
    "/documents/{document_id}",
    response_model=PropertyKnowledgeSourceResponse,
)
async def update_document_content(
    document_id: UUID,
    update: DocumentContentUpdate,
    context: KnowledgeEditor,
    session: DatabaseSession,
    settings: AppSettings,
) -> PropertyKnowledgeSourceResponse:
    service = PropertyCatalogService(session)
    try:
        property_id = await service.update_knowledge_source(
            tenant_id=context.tenant.id,
            document_id=document_id,
            actor_user_id=context.user.id,
            content=update.content,
            chunk_characters=settings.document_chunk_characters,
            chunk_overlap=settings.document_chunk_overlap,
        )
        property_detail = await service.get_property(
            tenant_id=context.tenant.id,
            property_id=property_id,
            can_edit=True,
        )
    except PropertyCatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PropertyCatalogConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return next(source for source in property_detail.knowledge_sources if source.id == document_id)
