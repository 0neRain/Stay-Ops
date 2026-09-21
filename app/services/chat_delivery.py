from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.models.domain import Integration
from app.models.enums import IntegrationProvider


@dataclass(frozen=True)
class ChatSendRequest:
    conversation_external_id: str
    content: str
    idempotency_key: str


@dataclass(frozen=True)
class ChatSendReceipt:
    provider_message_id: str
    sent_at: datetime


class ChatDeliveryError(Exception):
    """Raised when a configured provider cannot deliver an outgoing message."""


class ChatAdapterNotConfiguredError(ChatDeliveryError):
    """Raised when no adapter has been configured for an integration provider."""


class ChatProviderAdapter(Protocol):
    async def send_message(self, request: ChatSendRequest) -> ChatSendReceipt: ...


class ChatAdapterResolver(Protocol):
    def resolve(self, integration: Integration) -> ChatProviderAdapter: ...


class DemoChatAdapter:
    async def send_message(self, request: ChatSendRequest) -> ChatSendReceipt:
        return ChatSendReceipt(
            provider_message_id=f"demo-{request.idempotency_key}",
            sent_at=datetime.now(timezone.utc),
        )


class ConfiguredChatAdapterResolver:
    def resolve(self, integration: Integration) -> ChatProviderAdapter:
        if integration.provider == IntegrationProvider.DEMO:
            return DemoChatAdapter()
        raise ChatAdapterNotConfiguredError(
            f"No chat adapter is configured for {integration.provider.value}"
        )


def get_chat_adapter_resolver() -> ChatAdapterResolver:
    return ConfiguredChatAdapterResolver()
