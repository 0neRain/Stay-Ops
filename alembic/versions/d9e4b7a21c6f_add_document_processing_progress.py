"""add server-reported document processing progress

Revision ID: d9e4b7a21c6f
Revises: c31d7f42a9e0
Create Date: 2026-09-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9e4b7a21c6f"
down_revision: str | None = "c31d7f42a9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_documents",
        sa.Column("processing_progress", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "processing_stage",
            sa.String(length=80),
            server_default="queued",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("processing_eta_seconds", sa.Integer(), nullable=True),
    )
    op.alter_column("knowledge_documents", "processing_progress", server_default=None)
    op.alter_column("knowledge_documents", "processing_stage", server_default=None)


def downgrade() -> None:
    op.drop_column("knowledge_documents", "processing_eta_seconds")
    op.drop_column("knowledge_documents", "processing_stage")
    op.drop_column("knowledge_documents", "processing_progress")
