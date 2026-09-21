from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import AppSettings, AuthContext, DatabaseSession, require_roles
from app.models.enums import MembershipRole
from app.schemas.properties import HomeOnboardingResponse, HomeProfileUpdate
from app.services.answering import configured_answering_model
from app.services.property_onboarding import (
    PropertyOnboardingConflictError,
    PropertyOnboardingError,
    PropertyOnboardingExtractionError,
    PropertyOnboardingInputError,
    PropertyOnboardingNotFoundError,
    PropertyOnboardingService,
)

router = APIRouter(prefix="/properties", tags=["properties"])
PropertyEditor = Annotated[
    AuthContext,
    Depends(require_roles(MembershipRole.OWNER, MembershipRole.MANAGER)),
]


def _raise_onboarding_error(exc: PropertyOnboardingError) -> NoReturn:
    if isinstance(exc, PropertyOnboardingNotFoundError):
        status_code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, PropertyOnboardingConflictError):
        status_code = status.HTTP_409_CONFLICT
    elif isinstance(exc, PropertyOnboardingInputError):
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, PropertyOnboardingExtractionError):
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post(
    "/onboarding",
    response_model=HomeOnboardingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_home_onboarding(
    context: PropertyEditor,
    session: DatabaseSession,
) -> HomeOnboardingResponse:
    service = PropertyOnboardingService(session)
    return await service.create(
        tenant_id=context.tenant.id,
        actor_user_id=context.user.id,
    )


@router.get("/{property_id}/onboarding", response_model=HomeOnboardingResponse)
async def get_home_onboarding(
    property_id: UUID,
    context: PropertyEditor,
    session: DatabaseSession,
) -> HomeOnboardingResponse:
    service = PropertyOnboardingService(session)
    try:
        return await service.get(
            tenant_id=context.tenant.id,
            property_id=property_id,
        )
    except PropertyOnboardingError as exc:
        _raise_onboarding_error(exc)


@router.post("/{property_id}/onboarding/extract", response_model=HomeOnboardingResponse)
async def extract_home_onboarding(
    property_id: UUID,
    context: PropertyEditor,
    session: DatabaseSession,
    settings: AppSettings,
) -> HomeOnboardingResponse:
    service = PropertyOnboardingService(
        session,
        extraction_model=configured_answering_model(settings, max_tokens=1_600),
        extraction_timeout_seconds=settings.openrouter_timeout_seconds,
    )
    try:
        return await service.extract(
            tenant_id=context.tenant.id,
            property_id=property_id,
            actor_user_id=context.user.id,
        )
    except PropertyOnboardingError as exc:
        _raise_onboarding_error(exc)


@router.patch("/{property_id}/onboarding", response_model=HomeOnboardingResponse)
async def complete_home_onboarding(
    property_id: UUID,
    profile: HomeProfileUpdate,
    context: PropertyEditor,
    session: DatabaseSession,
) -> HomeOnboardingResponse:
    service = PropertyOnboardingService(session)
    try:
        return await service.complete(
            tenant_id=context.tenant.id,
            property_id=property_id,
            actor_user_id=context.user.id,
            profile=profile,
        )
    except PropertyOnboardingError as exc:
        _raise_onboarding_error(exc)
