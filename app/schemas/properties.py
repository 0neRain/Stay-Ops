from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DocumentProcessingStatus, PropertyOnboardingStatus

HOME_PROFILE_FIELDS = (
    "name",
    "timezone",
    "address",
    "property_type",
    "guest_capacity",
    "bedrooms",
    "bathrooms",
    "check_in_time",
    "check_out_time",
    "wifi_network",
    "parking_instructions",
    "access_instructions",
    "house_rules",
    "amenities",
    "emergency_information",
    "local_recommendations",
)


class HomeProfileDraft(BaseModel):
    name: str | None = None
    timezone: str | None = None
    address: str | None = None
    property_type: str | None = None
    guest_capacity: str | None = None
    bedrooms: str | None = None
    bathrooms: str | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    wifi_network: str | None = None
    parking_instructions: str | None = None
    access_instructions: str | None = None
    house_rules: str | None = None
    amenities: str | None = None
    emergency_information: str | None = None
    local_recommendations: str | None = None


class HomeProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    address: str = Field(default="", max_length=500)
    property_type: str = Field(default="", max_length=100)
    guest_capacity: str = Field(default="", max_length=40)
    bedrooms: str = Field(default="", max_length=40)
    bathrooms: str = Field(default="", max_length=40)
    check_in_time: str = Field(default="", max_length=80)
    check_out_time: str = Field(default="", max_length=80)
    wifi_network: str = Field(default="", max_length=160)
    parking_instructions: str = Field(default="", max_length=2_000)
    access_instructions: str = Field(default="", max_length=2_000)
    house_rules: str = Field(default="", max_length=5_000)
    amenities: str = Field(default="", max_length=5_000)
    emergency_information: str = Field(default="", max_length=3_000)
    local_recommendations: str = Field(default="", max_length=5_000)

    @field_validator("*")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class ExtractionEvidence(BaseModel):
    source_document_id: UUID
    source_filename: str
    excerpt: str = Field(max_length=500)
    confidence: float = Field(ge=0, le=1)


class OnboardingDocumentSummary(BaseModel):
    id: UUID
    filename: str | None
    processing_status: DocumentProcessingStatus
    processing_error: str | None


class HomeOnboardingResponse(BaseModel):
    id: UUID
    status: PropertyOnboardingStatus
    is_active: bool
    profile: HomeProfileDraft
    evidence: dict[str, ExtractionEvidence] = Field(default_factory=dict)
    documents: list[OnboardingDocumentSummary] = Field(default_factory=list)
    extraction_method: Literal["openrouter", "rules"] | None = None
    created_at: datetime
