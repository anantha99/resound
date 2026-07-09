"""Add operational runtime state.

Revision ID: 20260702_0005
Revises: 20260630_0004
Create Date: 2026-07-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260702_0005"
down_revision = "20260630_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_jobs", sa.Column("run_id", sa.String(length=256), nullable=True))
    op.create_index("ix_workflow_jobs_run_id", "workflow_jobs", ["run_id"])

    op.create_table(
        "source_health",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_id", sa.String(length=256), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "brand_id",
            "source_type",
            name="uq_source_health_scope",
        ),
    )
    for column in (
        "organization_id",
        "brand_id",
        "source_type",
        "provider",
        "status",
        "last_success_at",
        "last_failure_at",
        "last_run_id",
        "updated_at",
    ):
        op.create_index(f"ix_source_health_{column}", "source_health", [column])

    op.create_table(
        "public_feed_moderation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("organization_id", "brand_id", "signal_id", "action", "actor", "created_at"):
        op.create_index(
            f"ix_public_feed_moderation_events_{column}",
            "public_feed_moderation_events",
            [column],
        )

    op.create_index(
        "ix_listening_profile_suggestions_suggestion_type",
        "listening_profile_suggestions",
        ["suggestion_type"],
    )
    op.create_index(
        "ix_listening_profile_suggestions_created_at",
        "listening_profile_suggestions",
        ["created_at"],
    )
    op.create_index(
        "ix_listening_profile_suggestions_resolved_at",
        "listening_profile_suggestions",
        ["resolved_at"],
    )
    op.create_index(
        "ix_listening_profile_revisions_authored_by",
        "listening_profile_revisions",
        ["authored_by"],
    )
    op.create_index(
        "ix_listening_profile_revisions_created_at",
        "listening_profile_revisions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_listening_profile_revisions_created_at", table_name="listening_profile_revisions")
    op.drop_index("ix_listening_profile_revisions_authored_by", table_name="listening_profile_revisions")
    op.drop_index(
        "ix_listening_profile_suggestions_resolved_at",
        table_name="listening_profile_suggestions",
    )
    op.drop_index(
        "ix_listening_profile_suggestions_created_at",
        table_name="listening_profile_suggestions",
    )
    op.drop_index(
        "ix_listening_profile_suggestions_suggestion_type",
        table_name="listening_profile_suggestions",
    )
    op.drop_table("public_feed_moderation_events")
    op.drop_table("source_health")
    op.drop_index("ix_workflow_jobs_run_id", table_name="workflow_jobs")
    op.drop_column("workflow_jobs", "run_id")
