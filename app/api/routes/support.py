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
from app.models.domain import AuditEvent, Conversation, Escalation, Integration, Message
from app.models.enums import (
    ConversationStatus,
    DeliveryStatus,
    EscalationStatus,
    EscalationUrgency,
    IntegrationStatus,
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
    SendConversationMessageRequest,
    SendConversationMessageResponse,
)
from app.services.chat_delivery import (
    ChatAdapterNotConfiguredError,
    ChatAdapterResolver,
    ChatDeliveryError,
    ChatSendRequest,
    get_chat_adapter_resolver,
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
ChatAdapters = Annotated[ChatAdapterResolver, Depends(get_chat_adapter_resolver)]


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


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendConversationMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def send_conversation_message(
    conversation_id: UUID,
    payload: SendConversationMessageRequest,
    context: HumanOperator,
    session: DatabaseSession,
    adapters: ChatAdapters,
) -> SendConversationMessageResponse:
    conversation = await session.scalar(
        select(Conversation)
        .where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == context.tenant.id,
        )
        .with_for_update()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status == ConversationStatus.RESOLVED:
        raise HTTPException(status_code=409, detail="Conversation is already resolved")
    if conversation.human_locked_by_id not in {None, context.user.id}:
        raise HTTPException(status_code=409, detail="Conversation is assigned to another user")
    if conversation.integration_id is None or not conversation.external_id:
        raise HTTPException(status_code=409, detail="Conversation has no provider delivery channel")

    integration = await session.scalar(
        select(Integration).where(
            Integration.id == conversation.integration_id,
            Integration.tenant_id == context.tenant.id,
        )
    )
    if integration is None:
        raise HTTPException(status_code=409, detail="Conversation integration is unavailable")
    if integration.status != IntegrationStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Conversation integration is not active")
    try:
        adapter = adapters.resolve(integration)
    except ChatAdapterNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    message = Message(
        conversation_id=conversation.id,
        sender=MessageSender.HUMAN,
        sender_user_id=context.user.id,
        content=payload.content.strip(),
        delivery_status=DeliveryStatus.QUEUED,
    )
    session.add(message)
    conversation.status = ConversationStatus.HUMAN_ACTIVE
    conversation.human_locked_by_id = context.user.id
    conversation.human_locked_at = now
    await session.flush()
    session.add(
        AuditEvent(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            event_type="conversation.message_queued",
            entity_type="message",
            entity_id=message.id,
            details={
                "conversation_id": str(conversation.id),
                "provider": integration.provider.value,
            },
            created_at=now,
        )
    )
    # Commit the queued message before making an external call so every delivery
    # attempt has a durable local record and a stable provider idempotency key.
    await session.commit()

    try:
        receipt = await adapter.send_message(
            ChatSendRequest(
                conversation_external_id=conversation.external_id,
                content=message.content,
                idempotency_key=str(message.id),
            )
        )
    except ChatDeliveryError as exc:
        message.delivery_status = DeliveryStatus.FAILED
        session.add(
            AuditEvent(
                tenant_id=context.tenant.id,
                actor_user_id=context.user.id,
                event_type="conversation.message_failed",
                entity_type="message",
                entity_id=message.id,
                details={
                    "conversation_id": str(conversation.id),
                    "provider": integration.provider.value,
                    "error_type": type(exc).__name__,
                },
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
        raise HTTPException(status_code=502, detail="Chat provider failed to send message") from exc

    message.delivery_status = DeliveryStatus.SENT
    message.provider_message_id = receipt.provider_message_id
    message.provider_created_at = receipt.sent_at
    conversation.last_message_at = receipt.sent_at
    session.add(
        AuditEvent(
            tenant_id=context.tenant.id,
            actor_user_id=context.user.id,
            event_type="conversation.message_sent",
            entity_type="message",
            entity_id=message.id,
            details={
                "conversation_id": str(conversation.id),
                "provider": integration.provider.value,
                "provider_message_id": receipt.provider_message_id,
            },
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    return SendConversationMessageResponse(
        conversation_id=conversation.id,
        message_id=message.id,
        provider_message_id=receipt.provider_message_id,
        delivery_status=message.delivery_status,
        sent_at=receipt.sent_at,
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
