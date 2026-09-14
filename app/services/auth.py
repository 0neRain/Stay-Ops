import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    IssuedToken,
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
from app.models.auth import RefreshSession, Tenant, TenantMembership, User
from app.models.domain import AuditEvent
from app.models.enums import MembershipRole

DUMMY_PASSWORD_HASH = hash_password("not-a-real-password-for-timing-checks")


class AuthServiceError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(str(detail))


@dataclass(frozen=True)
class TokenPair:
    access: IssuedToken
    refresh: IssuedToken


@dataclass(frozen=True)
class AuthResult:
    user: User
    membership: TenantMembership
    tokens: TokenPair


def hash_ip_address(ip_address: str | None, settings: Settings) -> str | None:
    if not ip_address:
        return None
    value = f"{settings.jwt_secret_key}:{ip_address}".encode()
    return sha256(value).hexdigest()


def as_utc(value: datetime) -> datetime:
    """Normalize values from drivers that omit UTC tzinfo, such as SQLite in tests."""
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def make_tenant_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    return (slug or "organization")[:70]


async def _unique_tenant_slug(session: AsyncSession, name: str) -> str:
    base = make_tenant_slug(name)
    candidate = base
    suffix = 1
    while await session.scalar(select(Tenant.id).where(Tenant.slug == candidate)):
        suffix += 1
        candidate = f"{base[: 70 - len(str(suffix)) - 1]}-{suffix}"
    return candidate


def _audit(
    *,
    event_type: str,
    tenant_id: UUID | None,
    actor_user_id: UUID | None,
    ip_hash: str | None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        ip_hash=ip_hash,
        details=details or {},
        created_at=datetime.now(timezone.utc),
    )


async def _issue_token_pair(
    session: AsyncSession,
    *,
    settings: Settings,
    user: User,
    membership: TenantMembership,
    user_agent: str | None,
    ip_hash: str | None,
) -> TokenPair:
    access = issue_access_token(
        settings=settings,
        user_id=user.id,
        tenant_id=membership.tenant_id,
        role=membership.role.value,
    )
    refresh = issue_refresh_token(
        settings=settings,
        user_id=user.id,
        tenant_id=membership.tenant_id,
    )
    session.add(
        RefreshSession(
            user_id=user.id,
            tenant_id=membership.tenant_id,
            token_hash=hash_refresh_token(refresh.encoded),
            jti=refresh.jti,
            expires_at=refresh.expires_at,
            user_agent=user_agent[:512] if user_agent else None,
            ip_hash=ip_hash,
        )
    )
    return TokenPair(access=access, refresh=refresh)


async def register_owner(
    session: AsyncSession,
    *,
    settings: Settings,
    email: str,
    password: str,
    full_name: str,
    organization_name: str,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    normalized_email = normalize_email(email)
    try:
        validate_password(password, email=normalized_email)
    except ValueError as exc:
        raise AuthServiceError(422, str(exc)) from exc

    existing_user = await session.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None:
        raise AuthServiceError(409, "An account with this email already exists")

    tenant = Tenant(
        name=organization_name.strip(),
        slug=await _unique_tenant_slug(session, organization_name),
    )
    user = User(
        email=normalized_email,
        full_name=full_name.strip(),
        password_hash=hash_password(password),
    )
    session.add_all([tenant, user])
    await session.flush()

    membership = TenantMembership(
        tenant_id=tenant.id,
        user_id=user.id,
        role=MembershipRole.OWNER,
    )
    session.add(membership)
    await session.flush()

    ip_hash = hash_ip_address(ip_address, settings)
    tokens = await _issue_token_pair(
        session,
        settings=settings,
        user=user,
        membership=membership,
        user_agent=user_agent,
        ip_hash=ip_hash,
    )
    session.add(
        _audit(
            event_type="auth.registered",
            tenant_id=tenant.id,
            actor_user_id=user.id,
            ip_hash=ip_hash,
        )
    )

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AuthServiceError(409, "Account or organization already exists") from exc
    return AuthResult(user=user, membership=membership, tokens=tokens)


async def _select_membership(
    session: AsyncSession, *, user_id: UUID, tenant_id: UUID | None
) -> TenantMembership:
    statement = (
        select(TenantMembership)
        .join(Tenant, Tenant.id == TenantMembership.tenant_id)
        .where(
            TenantMembership.user_id == user_id,
            TenantMembership.is_active.is_(True),
            Tenant.is_active.is_(True),
        )
        .order_by(TenantMembership.created_at)
    )
    memberships = list((await session.scalars(statement)).all())
    if not memberships:
        raise AuthServiceError(403, "No active organization membership")
    if tenant_id is not None:
        membership = next((item for item in memberships if item.tenant_id == tenant_id), None)
        if membership is None:
            raise AuthServiceError(403, "No active membership for this organization")
        return membership
    if len(memberships) > 1:
        raise AuthServiceError(
            409,
            {
                "message": "tenant_id is required for accounts with multiple organizations",
                "tenant_ids": [str(item.tenant_id) for item in memberships],
            },
        )
    return memberships[0]


async def authenticate(
    session: AsyncSession,
    *,
    settings: Settings,
    email: str,
    password: str,
    tenant_id: UUID | None,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    normalized_email = normalize_email(email)
    user = await session.scalar(select(User).where(User.email == normalized_email))
    candidate_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_matches = verify_password(password, candidate_hash)
    if user is None or not password_matches:
        raise AuthServiceError(401, "Invalid email or password")
    if not user.is_active:
        raise AuthServiceError(403, "Account is disabled")

    membership = await _select_membership(session, user_id=user.id, tenant_id=tenant_id)
    now = datetime.now(timezone.utc)
    user.last_login_at = now
    ip_hash = hash_ip_address(ip_address, settings)
    tokens = await _issue_token_pair(
        session,
        settings=settings,
        user=user,
        membership=membership,
        user_agent=user_agent,
        ip_hash=ip_hash,
    )
    session.add(
        _audit(
            event_type="auth.logged_in",
            tenant_id=membership.tenant_id,
            actor_user_id=user.id,
            ip_hash=ip_hash,
        )
    )
    await session.commit()
    return AuthResult(user=user, membership=membership, tokens=tokens)


async def rotate_refresh_token(
    session: AsyncSession,
    *,
    settings: Settings,
    encoded_token: str,
    user_agent: str | None,
    ip_address: str | None,
) -> AuthResult:
    try:
        payload = decode_token(encoded_token, settings=settings, expected_type="refresh")
    except TokenValidationError as exc:
        raise AuthServiceError(401, str(exc)) from exc

    token_hash = hash_refresh_token(encoded_token)
    stored = await session.scalar(
        select(RefreshSession)
        .where(
            RefreshSession.token_hash == token_hash,
            RefreshSession.jti == UUID(payload["jti"]),
        )
        .with_for_update()
    )
    if stored is None:
        raise AuthServiceError(401, "Refresh session not found")

    now = datetime.now(timezone.utc)
    ip_hash = hash_ip_address(ip_address, settings)
    if stored.revoked_at is not None:
        await session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == stored.user_id,
                RefreshSession.tenant_id == stored.tenant_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        session.add(
            _audit(
                event_type="auth.refresh_reuse_detected",
                tenant_id=stored.tenant_id,
                actor_user_id=stored.user_id,
                ip_hash=ip_hash,
            )
        )
        await session.commit()
        raise AuthServiceError(401, "Refresh token reuse detected; sessions revoked")
    if as_utc(stored.expires_at) <= now:
        stored.revoked_at = now
        await session.commit()
        raise AuthServiceError(401, "Refresh token expired")

    user = await session.scalar(select(User).where(User.id == stored.user_id))
    if user is None or not user.is_active:
        raise AuthServiceError(401, "Account is unavailable")
    membership = await _select_membership(session, user_id=user.id, tenant_id=stored.tenant_id)

    tokens = await _issue_token_pair(
        session,
        settings=settings,
        user=user,
        membership=membership,
        user_agent=user_agent,
        ip_hash=ip_hash,
    )
    await session.flush()
    replacement = await session.scalar(
        select(RefreshSession).where(
            RefreshSession.token_hash == hash_refresh_token(tokens.refresh.encoded)
        )
    )
    stored.revoked_at = now
    stored.replaced_by_id = replacement.id if replacement else None
    session.add(
        _audit(
            event_type="auth.refresh_rotated",
            tenant_id=stored.tenant_id,
            actor_user_id=stored.user_id,
            ip_hash=ip_hash,
        )
    )
    await session.commit()
    return AuthResult(user=user, membership=membership, tokens=tokens)


async def revoke_refresh_token(
    session: AsyncSession,
    *,
    settings: Settings,
    encoded_token: str,
    ip_address: str | None,
) -> None:
    try:
        payload = decode_token(encoded_token, settings=settings, expected_type="refresh")
    except TokenValidationError:
        return

    stored = await session.scalar(
        select(RefreshSession)
        .where(
            RefreshSession.token_hash == hash_refresh_token(encoded_token),
            RefreshSession.jti == UUID(payload["jti"]),
        )
        .with_for_update()
    )
    if stored is None or stored.revoked_at is not None:
        return
    stored.revoked_at = datetime.now(timezone.utc)
    session.add(
        _audit(
            event_type="auth.logged_out",
            tenant_id=stored.tenant_id,
            actor_user_id=stored.user_id,
            ip_hash=hash_ip_address(ip_address, settings),
        )
    )
    await session.commit()
