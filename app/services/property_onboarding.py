import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import AuditEvent, KnowledgeDocument, KnowledgeVersion, Property
from app.models.enums import DocumentProcessingStatus, PropertyOnboardingStatus
from app.schemas.properties import (
    HOME_PROFILE_FIELDS,
    ExtractionEvidence,
    HomeOnboardingResponse,
    HomeProfileDraft,
    HomeProfileUpdate,
    OnboardingDocumentSummary,
)
from app.services.home_profile_extraction import HomeSourceDocument, extract_home_profile


class PropertyOnboardingError(Exception):
    pass


class PropertyOnboardingNotFoundError(PropertyOnboardingError):
    pass


class PropertyOnboardingConflictError(PropertyOnboardingError):
    pass


class PropertyOnboardingInputError(PropertyOnboardingError):
    pass


class PropertyOnboardingExtractionError(PropertyOnboardingError):
    pass


def onboarding_details(property_record: Property) -> dict[str, Any]:
    """Return a detached copy of the onboarding state stored on a property."""
    details = property_record.operational_details or {}
    onboarding = details.get("onboarding", {})
    return dict(onboarding) if isinstance(onboarding, dict) else {}


def onboarding_status(property_record: Property) -> PropertyOnboardingStatus:
    raw_status = onboarding_details(property_record).get("status")
    try:
        return PropertyOnboardingStatus(raw_status)
    except (TypeError, ValueError):
        return PropertyOnboardingStatus.DOCUMENTS


def can_attach_documents(property_record: Property) -> bool:
    """Keep knowledge uploads independent from the onboarding JSON representation."""
    if property_record.is_active:
        return True
    raw_status = onboarding_details(property_record).get("status")
    return raw_status in {
        PropertyOnboardingStatus.DOCUMENTS.value,
        PropertyOnboardingStatus.REVIEW.value,
    }


class PropertyOnboardingService:
    def __init__(self, session: AsyncSession, *, extraction_model: Any | None = None) -> None:
        self._session = session
        self._extraction_model = extraction_model

    async def create(self, *, tenant_id: UUID, actor_user_id: UUID) -> HomeOnboardingResponse:
        property_record = Property(
            tenant_id=tenant_id,
            name="Untitled home",
            timezone="UTC",
            address_json={},
            operational_details={
                "onboarding": {"status": PropertyOnboardingStatus.DOCUMENTS.value}
            },
            is_active=False,
        )
        self._session.add(property_record)
        await self._session.flush()
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                event_type="property.onboarding_started",
                entity_type="property",
                entity_id=property_record.id,
                details={},
            )
        )
        await self._session.commit()
        await self._session.refresh(property_record)
        return await self._response(property_record)

    async def get(self, *, tenant_id: UUID, property_id: UUID) -> HomeOnboardingResponse:
        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
        )
        return await self._response(property_record)

    async def extract(
        self,
        *,
        tenant_id: UUID,
        property_id: UUID,
        actor_user_id: UUID,
    ) -> HomeOnboardingResponse:
        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
            for_update=True,
        )
        self._ensure_draft(property_record)
        previous_status = onboarding_status(property_record)
        if previous_status == PropertyOnboardingStatus.EXTRACTING:
            raise PropertyOnboardingConflictError("Home profile extraction is already running")

        documents = await self._documents_for_property(property_record)
        if any(
            document.processing_status
            in {DocumentProcessingStatus.UPLOADED, DocumentProcessingStatus.PROCESSING}
            for document in documents
        ):
            raise PropertyOnboardingConflictError("Documents are still being processed")

        sources = await self._source_documents(documents)
        if not sources:
            raise PropertyOnboardingInputError("Upload at least one readable document")

        self._update_onboarding(
            property_record,
            status=PropertyOnboardingStatus.EXTRACTING.value,
            extraction_started_at=datetime.now(timezone.utc).isoformat(),
            extraction_stage_started_at=datetime.now(timezone.utc).isoformat(),
            extraction_progress=10,
            extraction_stage="extracting_profile",
            extraction_eta_seconds=20,
        )
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                event_type="property.profile_extraction_started",
                entity_type="property",
                entity_id=property_record.id,
                details={"document_count": len(sources)},
            )
        )
        # Release the property row before the provider call. The explicit EXTRACTING state
        # prevents competing writes without holding a database lock across network I/O.
        await self._session.commit()

        try:
            extracted = await extract_home_profile(sources, model=self._extraction_model)
        except asyncio.CancelledError:
            await self._restore_after_extraction_failure(
                tenant_id=tenant_id,
                property_id=property_id,
                actor_user_id=actor_user_id,
                previous_status=previous_status,
            )
            raise
        except Exception as exc:
            await self._restore_after_extraction_failure(
                tenant_id=tenant_id,
                property_id=property_id,
                actor_user_id=actor_user_id,
                previous_status=previous_status,
            )
            raise PropertyOnboardingExtractionError("Home profile extraction failed") from exc

        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
            for_update=True,
        )
        if onboarding_status(property_record) != PropertyOnboardingStatus.EXTRACTING:
            raise PropertyOnboardingConflictError("Home onboarding changed during extraction")

        self._update_onboarding(
            property_record,
            extraction_stage_started_at=datetime.now(timezone.utc).isoformat(),
            extraction_progress=90,
            extraction_stage="saving_profile",
            extraction_eta_seconds=2,
        )
        await self._session.commit()
        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
            for_update=True,
        )
        self._update_onboarding(
            property_record,
            status=PropertyOnboardingStatus.REVIEW.value,
            prefill=extracted.profile.model_dump(mode="json"),
            evidence={
                key: item.model_dump(mode="json") for key, item in extracted.evidence.items()
            },
            extraction_method=extracted.method,
            extracted_at=datetime.now(timezone.utc).isoformat(),
            extraction_progress=100,
            extraction_stage="complete",
            extraction_eta_seconds=0,
        )
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                event_type="property.profile_extracted",
                entity_type="property",
                entity_id=property_record.id,
                details={
                    "document_count": len(sources),
                    "field_count": len(extracted.evidence),
                    "method": extracted.method,
                },
            )
        )
        await self._session.commit()
        await self._session.refresh(property_record)
        return await self._response(property_record)

    async def complete(
        self,
        *,
        tenant_id: UUID,
        property_id: UUID,
        actor_user_id: UUID,
        profile: HomeProfileUpdate,
    ) -> HomeOnboardingResponse:
        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
            for_update=True,
        )
        self._ensure_draft(property_record)
        if onboarding_status(property_record) == PropertyOnboardingStatus.EXTRACTING:
            raise PropertyOnboardingConflictError("Home profile extraction is still running")

        profile_data = profile.model_dump(mode="json")
        self._update_onboarding(
            property_record,
            status=PropertyOnboardingStatus.COMPLETED.value,
            confirmed_profile=profile_data,
            confirmed_by=str(actor_user_id),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        property_record.name = profile.name
        property_record.timezone = profile.timezone
        property_record.address_json = {"formatted": profile.address} if profile.address else {}
        details = dict(property_record.operational_details or {})
        details.update(
            {
                key: value
                for key, value in profile_data.items()
                if key not in {"name", "timezone", "address"}
            }
        )
        property_record.operational_details = details
        property_record.is_active = True
        document_count = (
            await self._session.scalar(
                select(func.count(KnowledgeDocument.id)).where(
                    KnowledgeDocument.tenant_id == tenant_id,
                    KnowledgeDocument.property_id == property_id,
                )
            )
            or 0
        )
        self._session.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                event_type="property.onboarding_completed",
                entity_type="property",
                entity_id=property_record.id,
                details={"document_count": document_count},
            )
        )
        await self._session.commit()
        await self._session.refresh(property_record)
        return await self._response(property_record)

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
            raise PropertyOnboardingNotFoundError("Property not found")
        return property_record

    @staticmethod
    def _ensure_draft(property_record: Property) -> None:
        if (
            property_record.is_active
            or onboarding_status(property_record) == PropertyOnboardingStatus.COMPLETED
        ):
            raise PropertyOnboardingConflictError("This property onboarding is already complete")

    async def _documents_for_property(self, property_record: Property) -> list[KnowledgeDocument]:
        return list(
            (
                await self._session.scalars(
                    select(KnowledgeDocument)
                    .where(
                        KnowledgeDocument.tenant_id == property_record.tenant_id,
                        KnowledgeDocument.property_id == property_record.id,
                    )
                    .order_by(KnowledgeDocument.created_at)
                )
            ).all()
        )

    async def _source_documents(
        self, documents: list[KnowledgeDocument]
    ) -> list[HomeSourceDocument]:
        ready_documents = [
            document
            for document in documents
            if document.processing_status == DocumentProcessingStatus.NEEDS_REVIEW
        ]
        if not ready_documents:
            return []

        document_ids = [document.id for document in ready_documents]
        latest_versions = (
            select(
                KnowledgeVersion.document_id.label("document_id"),
                func.max(KnowledgeVersion.version).label("version"),
            )
            .where(KnowledgeVersion.document_id.in_(document_ids))
            .group_by(KnowledgeVersion.document_id)
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(KnowledgeDocument, KnowledgeVersion)
                .join(KnowledgeVersion, KnowledgeVersion.document_id == KnowledgeDocument.id)
                .join(
                    latest_versions,
                    (latest_versions.c.document_id == KnowledgeVersion.document_id)
                    & (latest_versions.c.version == KnowledgeVersion.version),
                )
                .where(KnowledgeDocument.id.in_(document_ids))
                .order_by(KnowledgeDocument.created_at)
            )
        ).all()
        return [
            HomeSourceDocument(
                id=document.id,
                filename=document.original_filename or document.title,
                content=version.content,
            )
            for document, version in rows
        ]

    async def _response(self, property_record: Property) -> HomeOnboardingResponse:
        onboarding = onboarding_details(property_record)
        status = onboarding_status(property_record)
        profile_key = (
            "confirmed_profile" if status == PropertyOnboardingStatus.COMPLETED else "prefill"
        )
        raw_profile = onboarding.get(profile_key, {})
        stored_profile = dict(raw_profile) if isinstance(raw_profile, dict) else {}
        if property_record.name != "Untitled home":
            stored_profile.setdefault("name", property_record.name)
        if property_record.timezone != "UTC":
            stored_profile.setdefault("timezone", property_record.timezone)
        formatted_address = property_record.address_json.get("formatted")
        if formatted_address:
            stored_profile.setdefault("address", formatted_address)

        evidence: dict[str, ExtractionEvidence] = {}
        raw_evidence = onboarding.get("evidence", {})
        if isinstance(raw_evidence, dict):
            for key, value in raw_evidence.items():
                if key not in HOME_PROFILE_FIELDS or not isinstance(value, dict):
                    continue
                try:
                    evidence[key] = ExtractionEvidence.model_validate(value)
                except ValidationError:
                    continue

        documents = await self._documents_for_property(property_record)
        extraction_method = onboarding.get("extraction_method")
        extraction_progress = onboarding.get("extraction_progress", 0)
        if not isinstance(extraction_progress, int):
            extraction_progress = 0
        extraction_progress = max(0, min(100, extraction_progress))
        extraction_stage = onboarding.get("extraction_stage")
        if not isinstance(extraction_stage, str):
            extraction_stage = None
        extraction_eta_seconds = onboarding.get("extraction_eta_seconds")
        if not isinstance(extraction_eta_seconds, int):
            extraction_eta_seconds = None
        if extraction_eta_seconds is not None and status == PropertyOnboardingStatus.EXTRACTING:
            stage_started_at = onboarding.get("extraction_stage_started_at")
            if isinstance(stage_started_at, str):
                try:
                    started_at = datetime.fromisoformat(stage_started_at)
                    if started_at.tzinfo is None:
                        started_at = started_at.replace(tzinfo=timezone.utc)
                    elapsed = int((datetime.now(timezone.utc) - started_at).total_seconds())
                    extraction_eta_seconds = max(0, extraction_eta_seconds - elapsed)
                except ValueError:
                    pass
        return HomeOnboardingResponse(
            id=property_record.id,
            status=status,
            is_active=property_record.is_active,
            profile=HomeProfileDraft.model_validate(stored_profile),
            evidence=evidence,
            documents=[
                OnboardingDocumentSummary(
                    id=document.id,
                    filename=document.original_filename,
                    processing_status=document.processing_status,
                    processing_error=document.processing_error,
                )
                for document in documents
            ],
            extraction_method=(
                extraction_method if extraction_method in {"openrouter", "rules"} else None
            ),
            extraction_progress=extraction_progress,
            extraction_stage=extraction_stage,
            extraction_eta_seconds=extraction_eta_seconds,
            created_at=property_record.created_at,
        )

    @staticmethod
    def _update_onboarding(property_record: Property, **updates: Any) -> None:
        details = dict(property_record.operational_details or {})
        onboarding = onboarding_details(property_record)
        onboarding.update(updates)
        details["onboarding"] = onboarding
        property_record.operational_details = details

    async def _restore_after_extraction_failure(
        self,
        *,
        tenant_id: UUID,
        property_id: UUID,
        actor_user_id: UUID,
        previous_status: PropertyOnboardingStatus,
    ) -> None:
        await self._session.rollback()
        property_record = await self._find_property(
            tenant_id=tenant_id,
            property_id=property_id,
            for_update=True,
        )
        if onboarding_status(property_record) == PropertyOnboardingStatus.EXTRACTING:
            self._update_onboarding(
                property_record,
                status=previous_status.value,
                extraction_stage="failed",
                extraction_eta_seconds=None,
            )
            self._session.add(
                AuditEvent(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    event_type="property.profile_extraction_failed",
                    entity_type="property",
                    entity_id=property_id,
                    details={},
                )
            )
            await self._session.commit()
