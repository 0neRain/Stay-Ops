from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEVELOPMENT_JWT_SECRET = "development-only-secret-change-before-production-1234567890"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "StayOps AI"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://stayops:stayops@localhost:5432/stayops"

    jwt_secret_key: str = Field(default=DEVELOPMENT_JWT_SECRET, min_length=32)
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "stayops-api"
    jwt_audience: str = "stayops-web"
    access_token_ttl_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=30)

    refresh_cookie_name: str = "stayops_refresh"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    refresh_cookie_domain: str | None = None

    cors_origins: list[str] = ["http://localhost:3000"]

    openrouter_api_key: str | None = None
    openrouter_chat_api_key: str | None = None
    openrouter_embedding_api_key: str | None = None
    openrouter_chat_model: str = "openai/gpt-5-mini"
    openrouter_embedding_model: str = "openai/text-embedding-3-small"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_app_url: str = "http://localhost:8000"
    openrouter_app_title: str = "StayOps AI"
    openrouter_chat_temperature: float = Field(default=0.1, ge=0, le=2)
    openrouter_chat_max_tokens: int = Field(default=600, ge=64, le=4096)
    openrouter_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    semantic_risk_threshold: float = Field(default=0.80, ge=0, le=1)

    @property
    def answering_api_key(self) -> str | None:
        return self.openrouter_chat_api_key or self.openrouter_api_key

    @property
    def embedding_api_key(self) -> str | None:
        return self.openrouter_embedding_api_key or self.openrouter_api_key

    @model_validator(mode="after")
    def reject_unsafe_production_settings(self) -> "Settings":
        if self.app_env == "production":
            if self.jwt_secret_key == DEVELOPMENT_JWT_SECRET:
                raise ValueError("JWT_SECRET_KEY must be replaced in production")
            if not self.refresh_cookie_secure:
                raise ValueError("REFRESH_COOKIE_SECURE must be true in production")
            if not self.cors_origins:
                raise ValueError("At least one explicit CORS origin is required")
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origins are forbidden in production")
        return self

    @property
    def refresh_cookie_path(self) -> str:
        return f"{self.api_v1_prefix}/auth"


@lru_cache
def get_settings() -> Settings:
    return Settings()
