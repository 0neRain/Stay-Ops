import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    AuditEvent,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeVersion,
    Property,
)
from app.models.enums import DocumentProcessingStatus, KnowledgeStatus
from app.schemas.properties import (
    HOME_PROFILE_FIELDS,
    HomeProfileDraft,
    HomeProfileUpdate,
    PropertyDetailResponse,
    PropertyKnowledgeSourceResponse,
    PropertySummaryResponse,
)
from app.services.document_ingestion import chunk_text
from app.services.profile_knowledge import PROFILE_DOCUMENT_TYPE, publish_confirmed_profile
from app.services.property_onboarding import onboarding_details


class PropertyCatalogNotFoundError(Exception):
    pass


class PropertyCatalogConflictError(Exception):
    pass


def _stored_profile(property_record: Property) -> HomeProfileDraft:
    details = dict(property_record.operational_details or {})
    onboarding = onboarding_details(property_record)
    raw_profile = onboarding.get("confirmed_profile") or onboarding.get("prefill") or {}
    values = dict(raw_profile) if isinstance(raw_profile, dict) else {}
    for field in HOME_PROFILE_FIELDS:
        if field in {"name", "timezone", "address"}:
            continue
        if isinstance(details.get(field), str):
            values.setdefault(field, details[field])
    if property_record.name != "Untitled home":
        values.setdefault("name", property_record.name)
    values.setdefault("timezone", property_record.timezone)
    formatted_address = property_record.address_json.get("formatted")
    if isinstance(formatted_address, str):
        values.setdefault("address", formatted_address)
    return HomeProfileDraft.model_validate(values)


class PropertyCatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_properties(self, *, tenant_id: UUID) -> list[PropertySummaryResponse]:
        properties = list(
            (
                await self._session.scalars(
                    select(Property)
                    .where(Property.tenant_id == tenant_id)
                    .order_by(Property.is_active.desc(), Property.name, Property.created_at)
                )
            ).all()
        )
        counts = {
            property_id: count
            for property_id, count in (
                await self._session.execute(
                    select(KnowledgeDocument.property_id, func.count(KnowledgeDocument.id))
                    .where(
                        KnowledgeDocument.tenant_id == tenant_id,
                        KnowledgeDocument.property_id.is_not(None),
                    )
                    .group_by(KnowledgeDocument.property_id)
                )
            ).all()
            if property_id is not None
        }
        return [
            PropertySummaryResponse(
                id=property_record.id,
                name=property_record.name,
                address=_stored_profile(property_record).address,
                property_type=_stored_profile(property_record).property_type,
                is_active=property_record.is_active,
                knowledge_source_count=counts.get(property_record.id, 0),
                updated_at=property_record.updated_at,
            )
            for property_record in properties
        ]

    async def get_property(
        self,
        *,
        tenant_id: UUID,
        property_id: UUID,
        can_edit: bool,
    ) -> PropertyDetailResponse:
        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
        )
        documents = list(
            (
                await self._session.scalars(
                    select(KnowledgeDocument)
                    .where(
                        KnowledgeDocument.tenant_id == tenant_id,
                        KnowledgeDocument.property_id == property_id,
                    )
                    .order_by(KnowledgeDocument.created_at.desc())
                )
            ).all()
        )
        versions: dict[UUID, KnowledgeVersion] = {}
        if documents:
            version_rows = list(
                (
                    await self._session.scalars(
                        select(KnowledgeVersion)
                        .where(
                            KnowledgeVersion.document_id.in_(
                                [document.id for document in documents]
                            )
                        )
                        .order_by(
                            KnowledgeVersion.document_id,
                            KnowledgeVersion.version.desc(),
                        )
                    )
                ).all()
            )
            for version in version_rows:
                versions.setdefault(version.document_id, version)
        return PropertyDetailResponse(
            id=property_record.id,
            name=property_record.name,
            is_active=property_record.is_active,
            profile=_stored_profile(property_record),
            knowledge_sources=[
                self._knowledge_source(document, versions.get(document.id), can_edit=can_edit)
                for document in documents
            ],
            can_edit=can_edit,
            created_at=property_record.created_at,
            updated_at=property_record.updated_at,
        )

    async def update_profile(
        self,
        *,
        tenant_id: UUID,
        property_id: UUID,
        actor_user_id: UUID,
        profile: HomeProfileUpdate,
    ) -> None:
        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
            for_update=True,
        )
        values = profile.model_dump(mode="json")
        property_record.name = profile.name
        property_record.timezone = profile.timezone
        property_record.address_json = {"formatted": profile.address} if profile.address else {}
        details = dict(property_record.operational_details or {})
        details.update(
            {
                key: value
                for key, value in values.items()
                if key not in {"name", "timezone", "address"}
            }
        )
        onboarding = onboarding_details(property_record)
        profile_key = "confirmed_profile" if property_record.is_active else "prefill"
        onboarding[profile_key] = values
        details["onboarding"] = onboarding
        property_record.operational_details = details
        if property_record.is_active:
            await publish_confirmed_profile(
                self._session,
                tenant_id=tenant_id,
                property_id=property_id,
                actor_user_id=actor_user_id,
                profile=values,
            )
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                event_type="property.profile_updated",
                entity_type="property",
                entity_id=property_id,
                details={"field_count": sum(bool(value) for value in values.values())},
            )
        )
        await self._session.commit()

    async def update_knowledge_source(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        actor_user_id: UUID,
        content: str,
        chunk_characters: int,
        chunk_overlap: int,
    ) -> UUID:
        document = await self._session.scalar(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.property_id.is_not(None),
            )
            .with_for_update()
        )
        if document is None:
            raise PropertyCatalogNotFoundError("Knowledge source not found")
        if document.document_type == PROFILE_DOCUMENT_TYPE:
            raise PropertyCatalogConflictError(
                "Edit the structured home profile instead of its generated knowledge source"
            )
        latest_version = await self._session.scalar(
            select(KnowledgeVersion)
            .where(KnowledgeVersion.document_id == document.id)
            .order_by(KnowledgeVersion.version.desc())
            .limit(1)
        )
        if latest_version is None:
            raise PropertyCatalogConflictError("Knowledge source has no readable content")
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if latest_version.content_sha256 == content_sha256:
            return document.property_id  # type: ignore[return-value]
        now = datetime.now(timezone.utc)
        approved = document.status == KnowledgeStatus.PUBLISHED
        version = KnowledgeVersion(
            document_id=document.id,
            version=latest_version.version + 1,
            content=content,
            content_sha256=content_sha256,
            source=latest_version.source,
            approved_by_id=actor_user_id if approved else None,
            approved_at=now if approved else None,
            embedding_status="pending",
            metadata_json={**dict(latest_version.metadata_json), "manually_edited": True},
        )
        self._session.add(version)
        await self._session.flush()
        chunks = chunk_text(
            content,
            maximum_characters=chunk_characters,
            overlap=chunk_overlap,
        )
        self._session.add_all(
            [
                KnowledgeChunk(
                    version_id=version.id,
                    tenant_id=tenant_id,
                    property_id=document.property_id,
                    chunk_index=index,
                    content=part,
                    token_count=max(1, len(part) // 4),
                    embedding=None,
                    metadata_json={
                        "source_kind": "manual_edit",
                        "requires_human_review": not approved,
                    },
                )
                for index, part in enumerate(chunks)
            ]
        )
        document.processing_status = DocumentProcessingStatus.NEEDS_REVIEW
        document.processing_progress = 100
        document.processing_stage = "complete"
        document.processing_eta_seconds = 0
        document.processing_error = None
        document.processed_at = now
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                event_type="knowledge.document_edited",
                entity_type="knowledge_document",
                entity_id=document.id,
                details={"version": version.version, "published": approved},
            )
        )
        await self._session.commit()
        assert document.property_id is not None
        return document.property_id

    async def _find_property(
        self,
        *,
        tenant_id: UUID,
        property_id: UUID,
        for_update: bool = False,
    ) -> Property:
        statement = select(Property).where(
            Property.id == property_id,
            Property.tenant_id == tenant_id,
        )
        if for_update:
            statement = statement.with_for_update()
        property_record = await self._session.scalar(statement)
        if property_record is None:
            raise PropertyCatalogNotFoundError("Property not found")
        return property_record

    @staticmethod
    def _knowledge_source(
        document: KnowledgeDocument,
        version: KnowledgeVersion | None,
        *,
        can_edit: bool,
    ) -> PropertyKnowledgeSourceResponse:
        is_profile = document.document_type == PROFILE_DOCUMENT_TYPE
        return PropertyKnowledgeSourceResponse(
            id=document.id,
            title=document.title,
            document_type=document.document_type,
            status=document.status,
            processing_status=document.processing_status,
            filename=document.original_filename,
            content=version.content if version else "",
            version=version.version if version else None,
            is_profile=is_profile,
            can_edit=can_edit and not is_profile and version is not None,
            updated_at=version.updated_at if version else document.updated_at,
        )
