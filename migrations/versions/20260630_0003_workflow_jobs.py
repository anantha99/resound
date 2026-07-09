"""Add workflow job command tracking.

Revision ID: 20260630_0003
Revises: 20260630_0002
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260630_0003"
down_revision = "20260630_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.String(length=256), nullable=False),
        sa.Column("workflow_type", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("task_queue", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workflow_id"),
    )
    for column in (
        "workflow_id",
        "workflow_type",
        "organization_id",
        "brand_id",
        "status",
        "created_at",
        "updated_at",
    ):
        op.create_index(f"ix_workflow_jobs_{column}", "workflow_jobs", [column])


def downgrade() -> None:
    op.drop_table("workflow_jobs")
