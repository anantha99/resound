"""Add agent and report artifacts.

Revision ID: 20260630_0002
Revises: 20260630_0001
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260630_0002"
down_revision = "20260630_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("agent_type", sa.String(length=64), nullable=False),
        sa.Column("user_goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    for column in ("organization_id", "brand_id", "agent_type", "status", "created_at"):
        op.create_index(f"ix_agent_sessions_{column}", "agent_sessions", [column])

    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_session_id", sa.Integer(), sa.ForeignKey("agent_sessions.id"), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("agent_session_id", "tool_name", "status", "created_at"):
        op.create_index(f"ix_agent_steps_{column}", "agent_steps", [column])

    op.create_table(
        "report_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("timeframe", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    for column in ("organization_id", "brand_id", "team_id", "role", "created_at"):
        op.create_index(f"ix_report_configs_{column}", "report_configs", [column])

    op.create_table(
        "report_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_config_id", sa.Integer(), sa.ForeignKey("report_configs.id"), nullable=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_freshness", sa.JSON(), nullable=False),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("internal_usefulness_rating", sa.Float(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
    )
    for column in (
        "report_config_id",
        "organization_id",
        "brand_id",
        "team_id",
        "role",
        "timeframe",
        "status",
        "generated_at",
    ):
        op.create_index(f"ix_report_runs_{column}", "report_runs", [column])

    op.create_table(
        "report_citations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("report_run_id", sa.Integer(), sa.ForeignKey("report_runs.id"), nullable=False),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("section_title", sa.String(length=128), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("full_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("report_run_id", "signal_id", "section_title", "source", "created_at"):
        op.create_index(f"ix_report_citations_{column}", "report_citations", [column])


def downgrade() -> None:
    op.drop_table("report_citations")
    op.drop_table("report_runs")
    op.drop_table("report_configs")
    op.drop_table("agent_steps")
    op.drop_table("agent_sessions")
