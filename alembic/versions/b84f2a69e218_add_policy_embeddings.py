"""add policy embeddings

Revision ID: b84f2a69e218
Revises: 736144fe11e8
Create Date: 2026-09-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b84f2a69e218"
down_revision: str | None = "736144fe11e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    urgency = postgresql.ENUM(
        "normal",
        "high",
        "emergency",
        name="escalation_urgency",
        create_type=False,
    )
    op.create_table(
        "policy_embeddings",
        sa.Column("policy_key", sa.String(length=160), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("urgency", urgency, nullable=False),
        sa.Column("example_text", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_embeddings")),
        sa.UniqueConstraint("policy_key", name="uq_policy_embeddings_policy_key"),
    )
    op.create_index(
        "ix_policy_embeddings_model_active",
        "policy_embeddings",
        ["model_name", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_policy_embeddings_vector_cosine",
        "policy_embeddings",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_policy_embeddings_vector_cosine", table_name="policy_embeddings")
    op.drop_index("ix_policy_embeddings_model_active", table_name="policy_embeddings")
    op.drop_table("policy_embeddings")
