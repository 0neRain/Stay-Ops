from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DeliveryStatus, EscalationStatus, EscalationUrgency


class ChatMessageRequest(BaseModel):
    property_id: UUID
    conversation_id: UUID | None = None
    content: str = Field(min_length=1, max_length=10_000)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be blank")
        return value


class KnowledgeCitation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    title: str
    score: float
    content: str


class ChatMessageResponse(BaseModel):
    conversation_id: UUID
    guest_message_id: UUID
    action: Literal["answered", "handoff"]
    response_message_id: UUID | None = None
    reply: str | None = None
    escalation_id: UUID | None = None
    reason: str | None = None
    urgency: EscalationUrgency | None = None
    citations: list[KnowledgeCitation] = Field(default_factory=list)


class SendConversationMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be blank")
        return value


class SendConversationMessageResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    provider_message_id: str
    delivery_status: DeliveryStatus
    sent_at: datetime


class EscalationQueueItem(BaseModel):
    id: UUID
    conversation_id: UUID
    status: EscalationStatus
    urgency: EscalationUrgency
    reason: str
    summary: str | None
    proposed_reply: str | None
    assigned_to_id: UUID | None
    resolved_by_id: UUID | None
    resolved_at: datetime | None
    created_at: datetime


class ResolveEscalationRequest(BaseModel):
    reply: str | None = Field(default=None, min_length=1, max_length=10_000)
    dismiss: bool = False


class EscalationResolutionResponse(BaseModel):
    escalation: EscalationQueueItem
    response_message_id: UUID | None = None
