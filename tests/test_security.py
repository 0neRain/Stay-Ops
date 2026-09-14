from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.config import DEVELOPMENT_JWT_SECRET, Settings
from app.core.security import (
    TokenValidationError,
    decode_token,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    issue_refresh_token,
    normalize_email,
    validate_password,
    verify_password,
)


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded != "correct horse battery staple"
    assert verify_password("correct horse battery staple", encoded)
    assert not verify_password("wrong password", encoded)


def test_password_policy_rejects_short_and_email_based_passwords() -> None:
    with pytest.raises(ValueError, match="at least 12"):
        validate_password("too-short")
    with pytest.raises(ValueError, match="email username"):
        validate_password("alexander-12345", email="alexander@example.com")


def test_email_normalization() -> None:
    assert normalize_email("  Owner@Example.COM ") == "owner@example.com"


def test_access_token_round_trip_and_type_enforcement() -> None:
    settings = Settings(app_env="test")
    user_id = uuid4()
    tenant_id = uuid4()
    issued = issue_access_token(
        settings=settings,
        user_id=user_id,
        tenant_id=tenant_id,
        role="owner",
    )
    payload = decode_token(issued.encoded, settings=settings, expected_type="access")
    assert payload["sub"] == str(user_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["role"] == "owner"
    assert issued.expires_at > datetime.now(timezone.utc)

    with pytest.raises(TokenValidationError, match="Incorrect token type"):
        decode_token(issued.encoded, settings=settings, expected_type="refresh")


def test_refresh_tokens_are_unique_and_hashable() -> None:
    settings = Settings(app_env="test")
    user_id = uuid4()
    tenant_id = uuid4()
    first = issue_refresh_token(settings=settings, user_id=user_id, tenant_id=tenant_id)
    second = issue_refresh_token(settings=settings, user_id=user_id, tenant_id=tenant_id)
    assert first.encoded != second.encoded
    assert len(hash_refresh_token(first.encoded)) == 64


def test_production_rejects_default_secret_and_insecure_cookie() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            app_env="production",
            jwt_secret_key=DEVELOPMENT_JWT_SECRET,
            refresh_cookie_secure=True,
        )
    with pytest.raises(ValueError, match="REFRESH_COOKIE_SECURE"):
        Settings(
            app_env="production",
            jwt_secret_key="a-production-secret-that-is-long-enough-123456789",
            refresh_cookie_secure=False,
        )
