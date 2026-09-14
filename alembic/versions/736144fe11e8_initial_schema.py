"""initial schema

Revision ID: 736144fe11e8
Revises:
Create Date: 2026-09-13 16:31:54.033486
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "736144fe11e8"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "audit_events",
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=160), nullable=False),
        sa.Column("entity_type", sa.String(length=120), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_events_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_audit_events_tenant_id_tenants"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"], unique=False
    )
    op.create_index(
        "ix_audit_events_tenant_created", "audit_events", ["tenant_id", "created_at"], unique=False
    )
    op.create_table(
        "integrations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("hostaway", "guesty", "demo", name="integration_provider"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "active", "error", "disabled", name="integration_status"),
            nullable=False,
        ),
        sa.Column("external_account_id", sa.String(length=160), nullable=True),
        sa.Column("credentials_encrypted", sa.Text(), nullable=True),
        sa.Column("webhook_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_integrations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_integrations")),
        sa.UniqueConstraint(
            "tenant_id", "provider", "external_account_id", name="uq_integrations_account"
        ),
    )
    op.create_index(
        "ix_integrations_tenant_status", "integrations", ["tenant_id", "status"], unique=False
    )
    op.create_table(
        "properties",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=160), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("address_json", sa.JSON(), nullable=False),
        sa.Column("operational_details", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_properties_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_properties")),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_properties_tenant_external"),
    )
    op.create_index(
        "ix_properties_tenant_active", "properties", ["tenant_id", "is_active"], unique=False
    )
    op.create_table(
        "refresh_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("jti", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_sessions.id"],
            name=op.f("fk_refresh_sessions_replaced_by_id_refresh_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_refresh_sessions_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_sessions")),
        sa.UniqueConstraint("jti", name=op.f("uq_refresh_sessions_jti")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_sessions_token_hash")),
    )
    op.create_index(
        "ix_refresh_sessions_expiry_revoked",
        "refresh_sessions",
        ["expires_at", "revoked_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_refresh_sessions_tenant_id"), "refresh_sessions", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_sessions_user_id"), "refresh_sessions", ["user_id"], unique=False
    )
    op.create_index(
        "ix_refresh_sessions_user_tenant",
        "refresh_sessions",
        ["user_id", "tenant_id"],
        unique=False,
    )
    op.create_table(
        "tenant_memberships",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "manager", "support", "viewer", name="membership_role"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_memberships_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tenant_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_memberships")),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )
    op.create_index(
        op.f("ix_tenant_memberships_tenant_id"), "tenant_memberships", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_tenant_memberships_user_active",
        "tenant_memberships",
        ["user_id", "is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tenant_memberships_user_id"), "tenant_memberships", ["user_id"], unique=False
    )
    op.create_table(
        "evaluation_cases",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("input_message", sa.Text(), nullable=False),
        sa.Column("expected_action", sa.String(length=80), nullable=False),
        sa.Column("expected_answer_contains", sa.JSON(), nullable=False),
        sa.Column("minimum_retrieval_score", sa.Float(), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_evaluation_cases_property_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_evaluation_cases_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_cases")),
    )
    op.create_index(
        "ix_evaluation_cases_scope",
        "evaluation_cases",
        ["tenant_id", "property_id", "is_active"],
        unique=False,
    )
    op.create_table(
        "knowledge_documents",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "pending_review", "published", "archived", name="knowledge_status"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_knowledge_documents_property_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_knowledge_documents_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
    )
    op.create_index(
        "ix_knowledge_documents_scope",
        "knowledge_documents",
        ["tenant_id", "property_id", "status"],
        unique=False,
    )
    op.create_table(
        "reservations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("guest_first_name", sa.String(length=120), nullable=True),
        sa.Column("guest_last_name", sa.String(length=120), nullable=True),
        sa.Column("guest_email", sa.String(length=320), nullable=True),
        sa.Column("arrival_date", sa.Date(), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "inquiry",
                "confirmed",
                "checked_in",
                "checked_out",
                "cancelled",
                "unknown",
                name="reservation_status",
            ),
            nullable=False,
        ),
        sa.Column("raw_data", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name=op.f("fk_reservations_integration_id_integrations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_reservations_property_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_reservations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        sa.UniqueConstraint("integration_id", "external_id", name="uq_reservations_external"),
    )
    op.create_index(
        op.f("ix_reservations_property_id"), "reservations", ["property_id"], unique=False
    )
    op.create_index(
        "ix_reservations_tenant_dates",
        "reservations",
        ["tenant_id", "arrival_date", "departure_date"],
        unique=False,
    )
    op.create_table(
        "conversations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=False),
        sa.Column("reservation_id", sa.Uuid(), nullable=True),
        sa.Column("integration_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(length=200), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "processing",
                "needs_human",
                "human_active",
                "resolved",
                name="conversation_status",
            ),
            nullable=False,
        ),
        sa.Column("human_locked_by_id", sa.Uuid(), nullable=True),
        sa.Column("human_locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["human_locked_by_id"],
            ["users.id"],
            name=op.f("fk_conversations_human_locked_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"],
            ["integrations.id"],
            name=op.f("fk_conversations_integration_id_integrations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_conversations_property_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.id"],
            name=op.f("fk_conversations_reservation_id_reservations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_conversations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("integration_id", "external_id", name="uq_conversations_external"),
    )
    op.create_index(
        "ix_conversations_last_message",
        "conversations",
        ["tenant_id", "last_message_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_tenant_status", "conversations", ["tenant_id", "status"], unique=False
    )
    op.create_table(
        "knowledge_versions",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("approved_by_id", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedding_status", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["approved_by_id"],
            ["users.id"],
            name=op.f("fk_knowledge_versions_approved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_versions_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_versions")),
        sa.UniqueConstraint(
            "document_id", "version", name="uq_knowledge_versions_document_version"
        ),
    )
    op.create_index(
        op.f("ix_knowledge_versions_document_id"),
        "knowledge_versions",
        ["document_id"],
        unique=False,
    )
    op.create_table(
        "escalations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("open", "assigned", "resolved", "dismissed", name="escalation_status"),
            nullable=False,
        ),
        sa.Column(
            "urgency",
            sa.Enum("normal", "high", "emergency", name="escalation_urgency"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("proposed_reply", sa.Text(), nullable=True),
        sa.Column("assigned_to_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["assigned_to_id"],
            ["users.id"],
            name=op.f("fk_escalations_assigned_to_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_escalations_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            name=op.f("fk_escalations_resolved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_escalations_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_escalations")),
    )
    op.create_index(
        op.f("ix_escalations_conversation_id"), "escalations", ["conversation_id"], unique=False
    )
    op.create_index(
        "ix_escalations_tenant_queue",
        "escalations",
        ["tenant_id", "status", "urgency", "created_at"],
        unique=False,
    )
    op.create_table(
        "knowledge_candidates",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("proposed_content", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", name="candidate_status"),
            nullable=False,
        ),
        sa.Column("reviewed_by_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_knowledge_candidates_conversation_id_conversations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_knowledge_candidates_property_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name=op.f("fk_knowledge_candidates_reviewed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_knowledge_candidates_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_candidates")),
    )
    op.create_index(
        "ix_knowledge_candidates_review",
        "knowledge_candidates",
        ["tenant_id", "status", "created_at"],
        unique=False,
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("property_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
            name=op.f("fk_knowledge_chunks_property_id_properties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_knowledge_chunks_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_versions.id"],
            name=op.f("fk_knowledge_chunks_version_id_knowledge_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
        sa.UniqueConstraint("version_id", "chunk_index", name="uq_knowledge_chunks_version_index"),
    )
    op.create_index(
        "ix_knowledge_chunks_scope", "knowledge_chunks", ["tenant_id", "property_id"], unique=False
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column(
            "sender",
            sa.Enum("guest", "agent", "human", "system", name="message_sender"),
            nullable=False,
        ),
        sa.Column("sender_user_id", sa.Uuid(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_redacted", sa.Text(), nullable=True),
        sa.Column("source_citations", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column(
            "delivery_status",
            sa.Enum("received", "queued", "sent", "failed", name="delivery_status"),
            nullable=False,
        ),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_user_id"],
            ["users.id"],
            name=op.f("fk_messages_sender_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "conversation_id", "provider_message_id", name="uq_messages_provider_message"
        ),
    )
    op.create_index(
        "ix_messages_conversation_created",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "feedback",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "rating", sa.Enum("positive", "negative", name="feedback_rating"), nullable=False
        ),
        sa.Column("corrected_answer", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_feedback_message_id_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by_id"],
            ["users.id"],
            name=op.f("fk_feedback_submitted_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_feedback_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index(op.f("ix_feedback_message_id"), "feedback", ["message_id"], unique=False)
    op.create_index(op.f("ix_feedback_tenant_id"), "feedback", ["tenant_id"], unique=False)
    op.create_table(
        "tool_runs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "success", "failed", name="tool_run_status"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=160), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_tool_runs_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name=op.f("fk_tool_runs_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tool_runs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_runs")),
    )
    op.create_index(
        "ix_tool_runs_conversation_created",
        "tool_runs",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_tool_runs_tenant_id"), "tool_runs", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tool_runs_tenant_id"), table_name="tool_runs")
    op.drop_index("ix_tool_runs_conversation_created", table_name="tool_runs")
    op.drop_table("tool_runs")
    op.drop_index(op.f("ix_feedback_tenant_id"), table_name="feedback")
    op.drop_index(op.f("ix_feedback_message_id"), table_name="feedback")
    op.drop_table("feedback")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_knowledge_chunks_scope", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_index("ix_knowledge_candidates_review", table_name="knowledge_candidates")
    op.drop_table("knowledge_candidates")
    op.drop_index("ix_escalations_tenant_queue", table_name="escalations")
    op.drop_index(op.f("ix_escalations_conversation_id"), table_name="escalations")
    op.drop_table("escalations")
    op.drop_index(op.f("ix_knowledge_versions_document_id"), table_name="knowledge_versions")
    op.drop_table("knowledge_versions")
    op.drop_index("ix_conversations_tenant_status", table_name="conversations")
    op.drop_index("ix_conversations_last_message", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_reservations_tenant_dates", table_name="reservations")
    op.drop_index(op.f("ix_reservations_property_id"), table_name="reservations")
    op.drop_table("reservations")
    op.drop_index("ix_knowledge_documents_scope", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    op.drop_index("ix_evaluation_cases_scope", table_name="evaluation_cases")
    op.drop_table("evaluation_cases")
    op.drop_index(op.f("ix_tenant_memberships_user_id"), table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_user_active", table_name="tenant_memberships")
    op.drop_index(op.f("ix_tenant_memberships_tenant_id"), table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_index("ix_refresh_sessions_user_tenant", table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_user_id"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_tenant_id"), table_name="refresh_sessions")
    op.drop_index("ix_refresh_sessions_expiry_revoked", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
    op.drop_index("ix_properties_tenant_active", table_name="properties")
    op.drop_table("properties")
    op.drop_index("ix_integrations_tenant_status", table_name="integrations")
    op.drop_table("integrations")
    op.drop_index("ix_audit_events_tenant_created", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_tenants_slug"), table_name="tenants")
    op.drop_table("tenants")
    for enum_name in (
        "tool_run_status",
        "feedback_rating",
        "candidate_status",
        "knowledge_status",
        "escalation_urgency",
        "escalation_status",
        "delivery_status",
        "message_sender",
        "conversation_status",
        "reservation_status",
        "integration_status",
        "integration_provider",
        "membership_role",
    ):
        op.execute(sa.text(f'DROP TYPE IF EXISTS "{enum_name}"'))
