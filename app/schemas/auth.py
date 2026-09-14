from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import MembershipRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str = Field(min_length=2, max_length=160)
    organization_name: str = Field(min_length=2, max_length=160)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    tenant_id: UUID | None = None


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str
    is_verified: bool
    created_at: datetime


class MembershipPublic(BaseModel):
    tenant_id: UUID
    tenant_name: str
    role: MembershipRole


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    active_tenant_id: UUID
    role: MembershipRole
    user: UserPublic


class MeResponse(BaseModel):
    user: UserPublic
    active_tenant_id: UUID
    role: MembershipRole
    memberships: list[MembershipPublic]


class MessageResponse(BaseModel):
    message: str
