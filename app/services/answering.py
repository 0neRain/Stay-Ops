from langchain_openrouter import ChatOpenRouter

from app.core.config import Settings


def configured_answering_model(settings: Settings) -> ChatOpenRouter | None:
    """Create the configured OpenRouter chat client without making a network request."""
    if not settings.answering_api_key:
        return None
    return ChatOpenRouter(
        api_key=settings.answering_api_key,
        base_url=settings.openrouter_base_url,
        app_url=settings.openrouter_app_url,
        app_title=settings.openrouter_app_title,
        model_name=settings.openrouter_chat_model,
        temperature=settings.openrouter_chat_temperature,
        max_tokens=settings.openrouter_chat_max_tokens,
        timeout=int(settings.openrouter_timeout_seconds),
        max_retries=2,
    )
