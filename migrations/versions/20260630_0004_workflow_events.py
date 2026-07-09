"""Add workflow event observability.

Revision ID: 20260630_0004
Revises: 20260630_0003
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260630_0004"
down_revision = "20260630_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_job_id", sa.Integer(), sa.ForeignKey("workflow_jobs.id"), nullable=False),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("workflow_job_id", "stage", "status", "created_at"):
        op.create_index(f"ix_workflow_events_{column}", "workflow_events", [column])


def downgrade() -> None:
    op.drop_table("workflow_events")
