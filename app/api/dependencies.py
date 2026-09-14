from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import TokenValidationError, decode_token
from app.db.session import get_db_session
from app.models.auth import Tenant, TenantMembership, User
from app.models.enums import MembershipRole

bearer_scheme = HTTPBearer(auto_error=False)
DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


@dataclass(frozen=True)
class AuthContext:
    user: User
    tenant: Tenant
    membership: TenantMembership


async def get_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: DatabaseSession,
    settings: AppSettings,
) -> AuthContext:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise unauthorized
    try:
        payload = decode_token(
            credentials.credentials,
            settings=settings,
            expected_type="access",
        )
        user_id = UUID(payload["sub"])
        tenant_id = UUID(payload["tenant_id"])
    except (TokenValidationError, KeyError, TypeError, ValueError):
        raise unauthorized from None

    row = (
        await session.execute(
            select(User, Tenant, TenantMembership)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                Tenant.id == tenant_id,
                Tenant.is_active.is_(True),
                TenantMembership.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise unauthorized
    user, tenant, membership = row
    return AuthContext(user=user, tenant=tenant, membership=membership)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


def require_roles(
    *allowed_roles: MembershipRole,
) -> Callable[[AuthContext], Coroutine[Any, Any, AuthContext]]:
    async def dependency(context: CurrentAuth) -> AuthContext:
        if context.membership.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient role")
        return context

    return dependency
