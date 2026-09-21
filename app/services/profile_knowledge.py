import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.domain import (
    AuditEvent,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeVersion,
)
from app.models.enums import DocumentProcessingStatus, KnowledgeStatus
from app.schemas.properties import HOME_PROFILE_FIELDS
from app.services.document_ingestion import chunk_text
from app.services.embeddings import EmbeddingProvider, EmbeddingProviderError

logger = structlog.get_logger()

PROFILE_DOCUMENT_TYPE = "property_profile"
PROFILE_SOURCE_KIND = "confirmed_property_profile"
PROFILE_CHUNK_CHARACTERS = 1_600
PROFILE_CHUNK_OVERLAP = 100

_FIELD_LABELS = {
    "name": "Home name",
    "timezone": "Timezone",
    "address": "Full address",
    "property_type": "Property type",
    "guest_capacity": "Maximum guests",
    "bedrooms": "Bedrooms",
    "bathrooms": "Bathrooms",
    "check_in_time": "Check-in time",
    "check_out_time": "Check-out time",
    "wifi_network": "Wi-Fi network",
    "parking_instructions": "Parking instructions",
    "access_instructions": "Arrival and access instructions",
    "house_rules": "House rules",
    "amenities": "Amenities",
    "emergency_information": "Emergency information",
    "local_recommendations": "Local recommendations",
}


@dataclass(frozen=True)
class ProfileKnowledgePublication:
    document_id: UUID
    version_id: UUID
    version: int
    created_version: bool


def _normalized_profile(profile: dict[str, Any]) -> dict[str, str]:
    return {
        field: value.strip()
        for field in HOME_PROFILE_FIELDS
        if isinstance((value := profile.get(field)), str) and value.strip()
    }


def render_profile_content(profile: dict[str, Any]) -> str:
    values = _normalized_profile(profile)
    return "\n\n".join(f"{_FIELD_LABELS[field]}: {values[field]}" for field in values)


def _render_profile_chunks(profile: dict[str, Any]) -> list[tuple[str, str]]:
    values = _normalized_profile(profile)
    rendered: list[tuple[str, str]] = []
    for field, value in values.items():
        text = f"{_FIELD_LABELS[field]}: {value}"
        parts = chunk_text(
            text,
            maximum_characters=PROFILE_CHUNK_CHARACTERS,
            overlap=PROFILE_CHUNK_OVERLAP,
        )
        rendered.extend((field, part) for part in parts)
    return rendered


async def publish_confirmed_profile(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    property_id: UUID,
    actor_user_id: UUID,
    profile: dict[str, Any],
) -> ProfileKnowledgePublication:
    """Publish the owner-confirmed form as the property's authoritative KB source."""

    now = datetime.now(timezone.utc)
    content = render_profile_content(profile)
    content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    name = _normalized_profile(profile).get("name", "Property")
    title = f"{name} — confirmed profile"

    document = await session.scalar(
        select(KnowledgeDocument)
        .where(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.property_id == property_id,
            KnowledgeDocument.document_type == PROFILE_DOCUMENT_TYPE,
        )
        .order_by(KnowledgeDocument.created_at)
        .limit(1)
    )
    if document is None:
        document = KnowledgeDocument(
            tenant_id=tenant_id,
            property_id=property_id,
            title=title,
            document_type=PROFILE_DOCUMENT_TYPE,
            status=KnowledgeStatus.PUBLISHED,
            processing_status=DocumentProcessingStatus.NEEDS_REVIEW,
            processing_progress=100,
            processing_stage="complete",
            processing_eta_seconds=0,
            uploaded_by_id=actor_user_id,
            processed_at=now,
        )
        session.add(document)
        await session.flush()
    else:
        document.title = title
        document.status = KnowledgeStatus.PUBLISHED
        document.processing_status = DocumentProcessingStatus.NEEDS_REVIEW
        document.processing_progress = 100
        document.processing_stage = "complete"
        document.processing_eta_seconds = 0
        document.processing_error = None
        document.processed_at = now

    latest_version = await session.scalar(
        select(KnowledgeVersion)
        .where(KnowledgeVersion.document_id == document.id)
        .order_by(KnowledgeVersion.version.desc())
        .limit(1)
    )
    created_version = latest_version is None or latest_version.content_sha256 != content_sha256
    if created_version:
        version = KnowledgeVersion(
            document_id=document.id,
            version=(latest_version.version + 1) if latest_version else 1,
            content=content,
            content_sha256=content_sha256,
            source=f"property-profile://{property_id}",
            approved_by_id=actor_user_id,
            approved_at=now,
            embedding_status="pending",
            metadata_json={
                "source_kind": PROFILE_SOURCE_KIND,
                "authoritative": True,
                "fields": list(_normalized_profile(profile)),
            },
        )
        session.add(version)
        await session.flush()
        chunks = _render_profile_chunks(profile)
        session.add_all(
            [
                KnowledgeChunk(
                    version_id=version.id,
                    tenant_id=tenant_id,
                    property_id=property_id,
                    chunk_index=index,
                    content=chunk_content,
                    token_count=max(1, len(chunk_content) // 4),
                    embedding=None,
                    metadata_json={
                        "source_kind": PROFILE_SOURCE_KIND,
                        "authoritative": True,
                        "profile_field": field,
                        "requires_human_review": False,
                    },
                )
                for index, (field, chunk_content) in enumerate(chunks)
            ]
        )
    else:
        assert latest_version is not None
        version = latest_version
        version.approved_by_id = actor_user_id
        version.approved_at = now

    source_documents = list(
        (
            await session.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeDocument.property_id == property_id,
                    KnowledgeDocument.id != document.id,
                )
            )
        ).all()
    )
    for source_document in source_documents:
        source_document.status = KnowledgeStatus.ARCHIVED

    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            event_type="property.profile_published",
            entity_type="knowledge_document",
            entity_id=document.id,
            details={
                "version": version.version,
                "created_version": created_version,
                "field_count": len(_normalized_profile(profile)),
                "archived_source_count": len(source_documents),
            },
        )
    )
    return ProfileKnowledgePublication(
        document_id=document.id,
        version_id=version.id,
        version=version.version,
        created_version=created_version,
    )


class ProfileKnowledgeIndexer:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_provider = embedding_provider

    async def process(self, *, tenant_id: UUID, property_id: UUID) -> None:
        async with self._session_factory() as session:
            document = await session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeDocument.property_id == property_id,
                    KnowledgeDocument.document_type == PROFILE_DOCUMENT_TYPE,
                    KnowledgeDocument.status == KnowledgeStatus.PUBLISHED,
                )
            )
            if document is None:
                return
            version = await session.scalar(
                select(KnowledgeVersion)
                .where(
                    KnowledgeVersion.document_id == document.id,
                    KnowledgeVersion.approved_at.is_not(None),
                )
                .order_by(KnowledgeVersion.version.desc())
                .limit(1)
            )
            if version is None or version.embedding_status == "ready":
                return
            chunks = list(
                (
                    await session.scalars(
                        select(KnowledgeChunk)
                        .where(KnowledgeChunk.version_id == version.id)
                        .order_by(KnowledgeChunk.chunk_index)
                    )
                ).all()
            )
            try:
                embeddings = await self._embedding_provider.embed_documents(
                    [chunk.content for chunk in chunks]
                )
                if len(embeddings) != len(chunks) or any(
                    len(embedding) != self._embedding_provider.dimensions
                    for embedding in embeddings
                ):
                    raise EmbeddingProviderError(
                        "Embedding response has an unexpected dimension"
                    )
            except EmbeddingProviderError as exc:
                logger.warning(
                    "property_profile_embedding_failed",
                    property_id=str(property_id),
                    error_type=type(exc).__name__,
                )
                return

            embedding_metadata = {
                "model": self._embedding_provider.model,
                "dimensions": self._embedding_provider.dimensions,
            }
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                chunk.embedding = embedding
                metadata = dict(chunk.metadata_json)
                metadata["embedding"] = embedding_metadata
                chunk.metadata_json = metadata
            metadata = dict(version.metadata_json)
            metadata["embedding"] = embedding_metadata
            version.metadata_json = metadata
            version.embedding_status = "ready"
            session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    actor_user_id=version.approved_by_id,
                    event_type="property.profile_embedded",
                    entity_type="knowledge_document",
                    entity_id=document.id,
                    details={"version": version.version, **embedding_metadata},
                )
            )
            await session.commit()
