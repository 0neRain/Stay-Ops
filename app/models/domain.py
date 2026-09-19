from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    CandidateStatus,
    ConversationStatus,
    DeliveryStatus,
    DocumentProcessingStatus,
    EscalationStatus,
    EscalationUrgency,
    FeedbackRating,
    IntegrationProvider,
    IntegrationStatus,
    KnowledgeStatus,
    MessageSender,
    ReservationStatus,
    ToolRunStatus,
)


def enum_values(enum: type[Enum]) -> list[str]:
    return [member.value for member in enum]


class Property(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_properties_tenant_external"),
        Index("ix_properties_tenant_active", "tenant_id", "is_active"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    address_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    operational_details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "provider", "external_account_id", name="uq_integrations_account"
        ),
        Index("ix_integrations_tenant_status", "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        SAEnum(
            IntegrationProvider,
            name="integration_provider",
            values_callable=enum_values,
        ),
        nullable=False,
    )
    status: Mapped[IntegrationStatus] = mapped_column(
        SAEnum(IntegrationStatus, name="integration_status", values_callable=enum_values),
        nullable=False,
        default=IntegrationStatus.PENDING,
    )
    external_account_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Reservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id", name="uq_reservations_external"),
        Index("ix_reservations_tenant_dates", "tenant_id", "arrival_date", "departure_date"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    guest_first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guest_last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guest_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    arrival_date: Mapped[date] = mapped_column(Date, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[ReservationStatus] = mapped_column(
        SAEnum(ReservationStatus, name="reservation_status", values_callable=enum_values),
        nullable=False,
        default=ReservationStatus.UNKNOWN,
    )
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("integration_id", "external_id", name="uq_conversations_external"),
        Index("ix_conversations_tenant_status", "tenant_id", "status"),
        Index("ix_conversations_last_message", "tenant_id", "last_message_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[UUID] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=False
    )
    reservation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True
    )
    integration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[ConversationStatus] = mapped_column(
        SAEnum(ConversationStatus, name="conversation_status", values_callable=enum_values),
        nullable=False,
        default=ConversationStatus.OPEN,
    )
    human_locked_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    human_locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "provider_message_id", name="uq_messages_provider_message"
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    sender: Mapped[MessageSender] = mapped_column(
        SAEnum(MessageSender, name="message_sender", values_callable=enum_values), nullable=False
    )
    sender_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        SAEnum(DeliveryStatus, name="delivery_status", values_callable=enum_values),
        nullable=False,
    )
    provider_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Escalation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "escalations"
    __table_args__ = (
        Index("ix_escalations_tenant_queue", "tenant_id", "status", "urgency", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[EscalationStatus] = mapped_column(
        SAEnum(EscalationStatus, name="escalation_status", values_callable=enum_values),
        nullable=False,
        default=EscalationStatus.OPEN,
    )
    urgency: Mapped[EscalationUrgency] = mapped_column(
        SAEnum(EscalationUrgency, name="escalation_urgency", values_callable=enum_values),
        nullable=False,
        default=EscalationUrgency.NORMAL,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_knowledge_documents_storage_key"),
        Index("ix_knowledge_documents_scope", "tenant_id", "property_id", "status"),
        Index(
            "ix_knowledge_documents_processing",
            "tenant_id",
            "processing_status",
            "created_at",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    document_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[KnowledgeStatus] = mapped_column(
        SAEnum(KnowledgeStatus, name="knowledge_status", values_callable=enum_values),
        nullable=False,
        default=KnowledgeStatus.DRAFT,
    )
    processing_status: Mapped[DocumentProcessingStatus] = mapped_column(
        SAEnum(
            DocumentProcessingStatus,
            name="document_processing_status",
            values_callable=enum_values,
        ),
        nullable=False,
        default=DocumentProcessingStatus.UPLOADED,
    )
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_error: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class KnowledgeVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_knowledge_versions_document_version"),
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class KnowledgeChunk(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index", name="uq_knowledge_chunks_version_index"),
        Index("ix_knowledge_chunks_scope", "tenant_id", "property_id"),
    )

    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_versions.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )


class KnowledgeCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_candidates"
    __table_args__ = (Index("ix_knowledge_candidates_review", "tenant_id", "status", "created_at"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=True
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[CandidateStatus] = mapped_column(
        SAEnum(CandidateStatus, name="candidate_status", values_callable=enum_values),
        nullable=False,
        default=CandidateStatus.PENDING,
    )
    reviewed_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Feedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback"

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    submitted_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[FeedbackRating] = mapped_column(
        SAEnum(FeedbackRating, name="feedback_rating", values_callable=enum_values), nullable=False
    )
    corrected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ToolRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tool_runs"
    __table_args__ = (Index("ix_tool_runs_conversation_created", "conversation_id", "created_at"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[ToolRunStatus] = mapped_column(
        SAEnum(ToolRunStatus, name="tool_run_status", values_callable=enum_values), nullable=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class PolicyEmbedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "policy_embeddings"
    __table_args__ = (
        UniqueConstraint("policy_key", name="uq_policy_embeddings_policy_key"),
        Index("ix_policy_embeddings_model_active", "model_name", "is_active"),
    )

    policy_key: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    urgency: Mapped[EscalationUrgency] = mapped_column(
        SAEnum(EscalationUrgency, name="escalation_urgency", values_callable=enum_values),
        nullable=False,
    )
    example_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvaluationCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_cases"
    __table_args__ = (Index("ix_evaluation_cases_scope", "tenant_id", "property_id", "is_active"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    property_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    input_message: Mapped[str] = mapped_column(Text, nullable=False)
    expected_action: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_answer_contains: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    minimum_retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
