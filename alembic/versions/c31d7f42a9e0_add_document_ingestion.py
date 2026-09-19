"""add document ingestion state and file metadata

Revision ID: c31d7f42a9e0
Revises: b84f2a69e218
Create Date: 2026-09-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c31d7f42a9e0"
down_revision: str | None = "b84f2a69e218"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    processing_status = postgresql.ENUM(
        "uploaded",
        "processing",
        "needs_review",
        "failed",
        name="document_processing_status",
        create_type=False,
    )
    processing_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "knowledge_documents",
        sa.Column(
            "processing_status",
            processing_status,
            server_default="uploaded",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("original_filename", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("storage_key", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("media_type", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("size_bytes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("uploaded_by_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("processing_error", sa.String(length=1000), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_knowledge_documents_uploaded_by_id_users"),
        "knowledge_documents",
        "users",
        ["uploaded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_knowledge_documents_storage_key",
        "knowledge_documents",
        ["storage_key"],
    )
    op.create_index(
        "ix_knowledge_documents_processing",
        "knowledge_documents",
        ["tenant_id", "processing_status", "created_at"],
        unique=False,
    )
    op.alter_column(
        "knowledge_chunks",
        "embedding",
        existing_type=Vector(1536),
        nullable=True,
    )
    op.alter_column("knowledge_documents", "processing_status", server_default=None)


def downgrade() -> None:
    op.alter_column(
        "knowledge_chunks",
        "embedding",
        existing_type=Vector(1536),
        nullable=False,
    )
    op.drop_index("ix_knowledge_documents_processing", table_name="knowledge_documents")
    op.drop_constraint(
        "uq_knowledge_documents_storage_key",
        "knowledge_documents",
        type_="unique",
    )
    op.drop_constraint(
        op.f("fk_knowledge_documents_uploaded_by_id_users"),
        "knowledge_documents",
        type_="foreignkey",
    )
    op.drop_column("knowledge_documents", "processing_error")
    op.drop_column("knowledge_documents", "processed_at")
    op.drop_column("knowledge_documents", "uploaded_by_id")
    op.drop_column("knowledge_documents", "file_sha256")
    op.drop_column("knowledge_documents", "size_bytes")
    op.drop_column("knowledge_documents", "media_type")
    op.drop_column("knowledge_documents", "storage_key")
    op.drop_column("knowledge_documents", "original_filename")
    op.drop_column("knowledge_documents", "processing_status")
    postgresql.ENUM(name="document_processing_status").drop(op.get_bind(), checkfirst=True)
