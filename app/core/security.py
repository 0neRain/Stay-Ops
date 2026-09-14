from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.config import Settings

password_hasher = PasswordHash.recommended()


class TokenValidationError(ValueError):
    """Raised when a bearer or refresh token cannot be trusted."""


@dataclass(frozen=True)
class IssuedToken:
    encoded: str
    jti: UUID
    expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def validate_password(password: str, *, email: str | None = None) -> None:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if len(password) > 128:
        raise ValueError("Password must not exceed 128 characters")
    if email:
        local_part = normalize_email(email).partition("@")[0]
        if len(local_part) >= 3 and local_part in password.casefold():
            raise ValueError("Password must not contain the email username")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_hasher.verify(password, password_hash)


def hash_refresh_token(encoded_token: str) -> str:
    return sha256(encoded_token.encode("utf-8")).hexdigest()


def _issue_token(
    *,
    settings: Settings,
    subject: UUID,
    token_type: Literal["access", "refresh"],
    lifetime: timedelta,
    tenant_id: UUID,
    role: str | None = None,
) -> IssuedToken:
    now = datetime.now(timezone.utc)
    expires_at = now + lifetime
    jti = uuid4()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "tenant_id": str(tenant_id),
        "type": token_type,
        "jti": str(jti),
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if role is not None:
        payload["role"] = role
    encoded = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return IssuedToken(encoded=encoded, jti=jti, expires_at=expires_at)


def issue_access_token(
    *, settings: Settings, user_id: UUID, tenant_id: UUID, role: str
) -> IssuedToken:
    return _issue_token(
        settings=settings,
        subject=user_id,
        token_type="access",
        lifetime=timedelta(minutes=settings.access_token_ttl_minutes),
        tenant_id=tenant_id,
        role=role,
    )


def issue_refresh_token(*, settings: Settings, user_id: UUID, tenant_id: UUID) -> IssuedToken:
    return _issue_token(
        settings=settings,
        subject=user_id,
        token_type="refresh",
        lifetime=timedelta(days=settings.refresh_token_ttl_days),
        tenant_id=tenant_id,
    )


def decode_token(
    encoded_token: str,
    *,
    settings: Settings,
    expected_type: Literal["access", "refresh"],
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            encoded_token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "tenant_id", "type", "jti", "iat", "nbf", "exp"]},
        )
    except InvalidTokenError as exc:
        raise TokenValidationError("Invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise TokenValidationError("Incorrect token type")

    try:
        UUID(payload["sub"])
        UUID(payload["tenant_id"])
        UUID(payload["jti"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenValidationError("Malformed token identity") from exc

    return payload
