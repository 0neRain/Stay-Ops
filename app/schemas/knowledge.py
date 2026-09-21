from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.enums import DocumentProcessingStatus, KnowledgeStatus


class DocumentResponse(BaseModel):
    id: UUID
    property_id: UUID | None
    title: str
    document_type: str
    status: KnowledgeStatus
    processing_status: DocumentProcessingStatus
    processing_progress: int
    processing_stage: str
    processing_eta_seconds: int | None
    original_filename: str | None
    media_type: str | None
    size_bytes: int | None
    file_sha256: str | None
    processed_at: datetime | None
    processing_error: str | None
    created_at: datetime
    extracted_characters: int | None = None
    chunk_count: int = 0
    embedding_status: str | None = None


class DocumentContentUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ValueError("Knowledge content cannot be blank")
        return normalized
