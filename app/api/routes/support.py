from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, select

from app.api.dependencies import (
    AppSettings,
    AuthContext,
    CurrentAuth,
    DatabaseSession,
    require_roles,
)
from app.models.domain import AuditEvent, Conversation, Escalation, Message
from app.models.enums import (
    ConversationStatus,
    DeliveryStatus,
    EscalationStatus,
    EscalationUrgency,
    MembershipRole,
    MessageSender,
)
from app.schemas.support import (
    ChatMessageRequest,
    ChatMessageResponse,
    EscalationQueueItem,
    EscalationResolutionResponse,
    KnowledgeCitation,
    ResolveEscalationRequest,
)
from app.services.embeddings import configured_embedding_provider
from app.services.support_pipeline import SupportPipelineError, process_guest_message

router = APIRouter(tags=["guest support"])
HumanOperator = Annotated[
    AuthContext,
    Depends(
        require_roles(
            MembershipRole.OWNER,
            MembershipRole.MANAGER,
            MembershipRole.SUPPORT,
        )
    ),
]


def _queue_item(escalation: Escalation) -> EscalationQueueItem:
    return EscalationQueueItem(
        id=escalation.id,
        conversation_id=escalation.conversation_id,
        status=escalation.status,
        urgency=escalation.urgency,
        reason=escalation.reason,
        summary=escalation.summary,
        proposed_reply=escalation.proposed_reply,
        assigned_to_id=escalation.assigned_to_id,
        resolved_by_id=escalation.resolved_by_id,
        resolved_at=escalation.resolved_at,
        created_at=escalation.created_at,
    )


@router.post(
    "/chat/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_guest_message(
    payload: ChatMessageRequest,
    context: CurrentAuth,
    session: DatabaseSession,
    settings: AppSettings,
) -> ChatMessageResponse:
    try:
        result = await process_guest_message(
            session,
            tenant_id=context.tenant.id,
            property_id=payload.property_id,
            conversation_id=payload.conversation_id,
            content=payload.content,
            embedding_provider=configured_embedding_provider(settings),
            semantic_risk_threshold=settings.semantic_risk_threshold,
        )
    except SupportPipelineError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return ChatMessageResponse(
        conversation_id=result.conversation.id,
        guest_message_id=result.guest_message.id,
        action=result.decision.action,
        response_message_id=result.response_message.id if result.response_message else None,
        reply=result.decision.answer,
        escalation_id=result.escalation.id if result.escalation else None,
        reason=result.decision.reason,
        urgency=result.decision.urgency,
        citations=[
            KnowledgeCitation(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                version_id=hit.version_id,
                title=hit.title,
                score=hit.score,
                content=hit.content,
            )
            for hit in result.decision.hits
        ],
    )


@router.get("/escalations", response_model=list[EscalationQueueItem])
async def list_escalations(
    context: CurrentAuth,
    session: DatabaseSession,
    escalation_status: Annotated[EscalationStatus | None, Query(alias="status")] = None,
) -> list[EscalationQueueItem]:
    statement = select(Escalation).where(Escalation.tenant_id == context.tenant.id)
    if escalation_status is None:
        statement = statement.where(
            Escalation.status.in_([EscalationStatus.OPEN, EscalationStatus.ASSIGNED])
        )
    else:
        statement = statement.where(Escalation.status == escalation_status)
    urgency_order = case(
        (Escalation.urgency == EscalationUrgency.EMERGENCY, 0),
        (Escalation.urgency == EscalationUrgency.HIGH, 1),
        else_=2,
    )
    escalations = list(
        (await session.scalars(statement.order_by(urgency_order, Escalation.created_at))).all()
    )
    return [_queue_item(escalation) for escalation in escalations]


async def _locked_escalation(
    session: DatabaseSession,
    *,
    tenant_id: UUID,
    escalation_id: UUID,
) -> Escalation:
    escalation = await session.scalar(
        select(Escalation)
        .where(Escalation.id == escalation_id, Escalation.tenant_id == tenant_id)
        .with_for_update()
    )
    if escalation is None:
        raise HTTPException(status_code=404, detail="Escalation not found")
    return escalation


@router.post("/escalations/{escalation_id}/claim", response_model=EscalationQueueItem)
async def claim_escalation(
    escalation_id: UUID,
    context: HumanOperator,
    session: DatabaseSession,
) -> EscalationQueueItem:
    escalation = await _locked_escalation(
        session,
        tenant_id=context.tenant.id,
        escalation_id=escalation_id,
    )
    if escalation.status in {EscalationStatus.RESOLVED, EscalationStatus.DISMISSED}:
        raise HTTPException(status_code=409, detail="Escalation is already closed")
    if escalation.assigned_to_id not in {None, context.user.id}:
        raise HTTPException(status_code=409, detail="Escalation is assigned to another user")

    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == escalation.conversation_id,
            Conversation.tenant_id == context.tenant.id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=409, detail="Escalation conversation is unavailable")
    now = datetime.now(timezone.utc)
    escalation.status = EscalationStatus.ASSIGNED
    escalation.assigned_to_id = context.user.id
    conversation.status = ConversationStatus.HUMAN_ACTIVE
    conversation.human_locked_by_id = context.user.id
    conversation.human_locked_at = now
    session.add(
        AuditEvent(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            event_type="escalation.claimed",
            entity_type="escalation",
            entity_id=escalation.id,
            created_at=now,
        )
    )
    await session.commit()
    return _queue_item(escalation)


@router.post(
    "/escalations/{escalation_id}/resolve",
    response_model=EscalationResolutionResponse,
)
async def resolve_escalation(
    escalation_id: UUID,
    payload: ResolveEscalationRequest,
    context: HumanOperator,
    session: DatabaseSession,
) -> EscalationResolutionResponse:
    escalation = await _locked_escalation(
        session,
        tenant_id=context.tenant.id,
        escalation_id=escalation_id,
    )
    if escalation.status in {EscalationStatus.RESOLVED, EscalationStatus.DISMISSED}:
        raise HTTPException(status_code=409, detail="Escalation is already closed")
    if escalation.assigned_to_id not in {None, context.user.id}:
        raise HTTPException(status_code=409, detail="Escalation is assigned to another user")

    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == escalation.conversation_id,
            Conversation.tenant_id == context.tenant.id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=409, detail="Escalation conversation is unavailable")

    now = datetime.now(timezone.utc)
    response_message: Message | None = None
    if payload.reply:
        response_message = Message(
            conversation_id=conversation.id,
            sender=MessageSender.HUMAN,
            sender_user_id=context.user.id,
            content=payload.reply,
            delivery_status=DeliveryStatus.SENT,
        )
        session.add(response_message)
        conversation.last_message_at = now
    escalation.status = EscalationStatus.DISMISSED if payload.dismiss else EscalationStatus.RESOLVED
    escalation.resolved_by_id = context.user.id
    escalation.resolved_at = now
    conversation.status = ConversationStatus.RESOLVED
    conversation.human_locked_by_id = None
    conversation.human_locked_at = None
    session.add(
        AuditEvent(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            event_type=f"escalation.{escalation.status.value}",
            entity_type="escalation",
            entity_id=escalation.id,
            details={"response_message_id": str(response_message.id) if response_message else None},
            created_at=now,
        )
    )
    await session.commit()
    return EscalationResolutionResponse(
        escalation=_queue_item(escalation),
        response_message_id=response_message.id if response_message else None,
    )
