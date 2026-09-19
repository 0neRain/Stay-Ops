from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

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
