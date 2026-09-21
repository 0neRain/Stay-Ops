from datetime import datetime, timezone
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app
from app.models.domain import AuditEvent, Conversation, Integration, Message, Property
from app.models.enums import (
    ConversationStatus,
    DeliveryStatus,
    IntegrationProvider,
    IntegrationStatus,
    MessageSender,
)
from app.services.chat_delivery import (
    ChatDeliveryError,
    ChatSendReceipt,
    ChatSendRequest,
    get_chat_adapter_resolver,
)

REGISTRATION = {
    "email": "delivery-owner@example.com",
    "password": "correct horse battery staple",
    "full_name": "Delivery Owner",
    "organization_name": "Delivery Stays",
}


class RecordingChatAdapter:
    def __init__(self, *, error: ChatDeliveryError | None = None) -> None:
        self.error = error
        self.requests: list[ChatSendRequest] = []

    async def send_message(self, request: ChatSendRequest) -> ChatSendReceipt:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return ChatSendReceipt(
            provider_message_id="provider-message-123",
            sent_at=datetime(2026, 9, 21, 20, 30, tzinfo=timezone.utc),
        )


class RecordingResolver:
    def __init__(self, adapter: RecordingChatAdapter) -> None:
        self.adapter = adapter
        self.integrations: list[Integration] = []

    def resolve(self, integration: Integration) -> RecordingChatAdapter:
        self.integrations.append(integration)
        return self.adapter


async def _register(client: httpx.AsyncClient) -> tuple[dict[str, str], UUID, UUID]:
    response = await client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 201
    body = response.json()
    return (
        {"Authorization": f"Bearer {body['access_token']}"},
        UUID(body["active_tenant_id"]),
        UUID(body["user"]["id"]),
    )


async def _seed_conversation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
) -> UUID:
    async with session_factory() as session:
        integration = Integration(
            tenant_id=tenant_id,
            provider=IntegrationProvider.DEMO,
            status=IntegrationStatus.ACTIVE,
            external_account_id="demo-account",
        )
        property_record = Property(tenant_id=tenant_id, name="Delivery House", timezone="UTC")
        session.add_all([integration, property_record])
        await session.flush()
        conversation = Conversation(
            tenant_id=tenant_id,
            property_id=property_record.id,
            integration_id=integration.id,
            external_id="provider-conversation-456",
            status=ConversationStatus.OPEN,
        )
        session.add(conversation)
        await session.commit()
        return conversation.id


async def test_send_message_calls_provider_adapter_and_persists_receipt(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, tenant_id, user_id = await _register(api_client)
    conversation_id = await _seed_conversation(db_session_factory, tenant_id=tenant_id)
    adapter = RecordingChatAdapter()
    resolver = RecordingResolver(adapter)
    app.dependency_overrides[get_chat_adapter_resolver] = lambda: resolver

    response = await api_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "  We will meet you at the front door.  "},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["conversation_id"] == str(conversation_id)
    assert body["provider_message_id"] == "provider-message-123"
    assert body["delivery_status"] == "sent"
    assert len(resolver.integrations) == 1
    assert len(adapter.requests) == 1
    assert adapter.requests[0].conversation_external_id == "provider-conversation-456"
    assert adapter.requests[0].content == "We will meet you at the front door."
    assert adapter.requests[0].idempotency_key == body["message_id"]

    async with db_session_factory() as session:
        message = await session.get(Message, UUID(body["message_id"]))
        conversation = await session.get(Conversation, conversation_id)
        events = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.entity_id == UUID(body["message_id"]))
            )
        )
    assert message is not None
    assert message.sender == MessageSender.HUMAN
    assert message.sender_user_id == user_id
    assert message.content == "We will meet you at the front door."
    assert message.delivery_status == DeliveryStatus.SENT
    assert message.provider_message_id == "provider-message-123"
    assert conversation is not None
    assert conversation.status == ConversationStatus.HUMAN_ACTIVE
    assert conversation.human_locked_by_id == user_id
    assert [event.event_type for event in events] == [
        "conversation.message_queued",
        "conversation.message_sent",
    ]


async def test_send_message_records_failed_provider_delivery(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    headers, tenant_id, _ = await _register(api_client)
    conversation_id = await _seed_conversation(db_session_factory, tenant_id=tenant_id)
    adapter = RecordingChatAdapter(error=ChatDeliveryError("provider unavailable"))
    app.dependency_overrides[get_chat_adapter_resolver] = lambda: RecordingResolver(adapter)

    response = await api_client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Please try the side entrance."},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Chat provider failed to send message"
    assert len(adapter.requests) == 1
    async with db_session_factory() as session:
        message = await session.scalar(
            select(Message).where(Message.conversation_id == conversation_id)
        )
        events = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.entity_id == message.id)
            )
        )
    assert message is not None
    assert message.delivery_status == DeliveryStatus.FAILED
    assert message.provider_message_id is None
    assert [event.event_type for event in events] == [
        "conversation.message_queued",
        "conversation.message_failed",
    ]
