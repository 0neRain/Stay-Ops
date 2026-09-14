from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.dependencies import AppSettings, CurrentAuth, DatabaseSession
from app.models.auth import Tenant, TenantMembership
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MembershipPublic,
    MeResponse,
    MessageResponse,
    RegisterRequest,
    UserPublic,
)
from app.services.auth import (
    AuthResult,
    AuthServiceError,
    authenticate,
    register_owner,
    revoke_refresh_token,
    rotate_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_refresh_cookie(
    response: Response, *, encoded_token: str, expires_at: datetime, settings: AppSettings
) -> None:
    max_age = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=encoded_token,
        max_age=max_age,
        expires=expires_at,
        path=settings.refresh_cookie_path,
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, settings: AppSettings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        domain=settings.refresh_cookie_domain,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _auth_response(result: AuthResult, settings: AppSettings) -> AuthResponse:
    return AuthResponse(
        access_token=result.tokens.access.encoded,
        expires_in=settings.access_token_ttl_minutes * 60,
        active_tenant_id=result.membership.tenant_id,
        role=result.membership.role,
        user=UserPublic.model_validate(result.user),
    )


def _raise_service_error(exc: AuthServiceError) -> None:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    raise HTTPException(status_code=exc.status_code, detail=exc.detail, headers=headers) from exc


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: AppSettings,
) -> AuthResponse:
    try:
        result = await register_owner(
            session,
            settings=settings,
            email=str(payload.email),
            password=payload.password,
            full_name=payload.full_name,
            organization_name=payload.organization_name,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except AuthServiceError as exc:
        _raise_service_error(exc)
    _set_refresh_cookie(
        response,
        encoded_token=result.tokens.refresh.encoded,
        expires_at=result.tokens.refresh.expires_at,
        settings=settings,
    )
    return _auth_response(result, settings)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: AppSettings,
) -> AuthResponse:
    try:
        result = await authenticate(
            session,
            settings=settings,
            email=str(payload.email),
            password=payload.password,
            tenant_id=payload.tenant_id,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except AuthServiceError as exc:
        _raise_service_error(exc)
    _set_refresh_cookie(
        response,
        encoded_token=result.tokens.refresh.encoded,
        expires_at=result.tokens.refresh.expires_at,
        settings=settings,
    )
    return _auth_response(result, settings)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: AppSettings,
) -> AuthResponse:
    encoded_token = request.cookies.get(settings.refresh_cookie_name)
    if not encoded_token:
        raise HTTPException(status_code=401, detail="Refresh token is missing")
    try:
        result = await rotate_refresh_token(
            session,
            settings=settings,
            encoded_token=encoded_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=_client_ip(request),
        )
    except AuthServiceError as exc:
        _clear_refresh_cookie(response, settings)
        _raise_service_error(exc)
    _set_refresh_cookie(
        response,
        encoded_token=result.tokens.refresh.encoded,
        expires_at=result.tokens.refresh.expires_at,
        settings=settings,
    )
    return _auth_response(result, settings)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: AppSettings,
) -> MessageResponse:
    encoded_token = request.cookies.get(settings.refresh_cookie_name)
    if encoded_token:
        await revoke_refresh_token(
            session,
            settings=settings,
            encoded_token=encoded_token,
            ip_address=_client_ip(request),
        )
    _clear_refresh_cookie(response, settings)
    return MessageResponse(message="Logged out")


@router.get("/me", response_model=MeResponse)
async def me(context: CurrentAuth, session: DatabaseSession) -> MeResponse:
    rows = (
        await session.execute(
            select(TenantMembership, Tenant)
            .join(Tenant, Tenant.id == TenantMembership.tenant_id)
            .where(
                TenantMembership.user_id == context.user.id,
                TenantMembership.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
            .order_by(Tenant.name)
        )
    ).all()
    memberships = [
        MembershipPublic(
            tenant_id=membership.tenant_id,
            tenant_name=tenant.name,
            role=membership.role,
        )
        for membership, tenant in rows
    ]
    return MeResponse(
        user=UserPublic.model_validate(context.user),
        active_tenant_id=context.tenant.id,
        role=context.membership.role,
        memberships=memberships,
    )
