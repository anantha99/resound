"""Initial production backend schema.

Revision ID: 20260630_0001
Revises:
Create Date: 2026-06-30
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260630_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])
    op.create_index("ix_organizations_created_at", "organizations", ["created_at"])

    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_teams_org_slug"),
    )
    op.create_index("ix_teams_organization_id", "teams", ["organization_id"])
    op.create_index("ix_teams_slug", "teams", ["slug"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("email", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_users_external_id", "users", ["external_id"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "team_id", "user_id", name="uq_memberships_scope"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_index("ix_memberships_team_id", "memberships", ["team_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "slug", name="uq_brands_org_slug"),
    )
    op.create_index("ix_brands_organization_id", "brands", ["organization_id"])
    op.create_index("ix_brands_slug", "brands", ["slug"])

    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("brand_slug", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_mode", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("external_id", sa.String(length=256), nullable=False),
        sa.Column("dedupe_key", sa.String(length=320), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author_handle", sa.String(length=256), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("dedupe_key"),
    )
    for column in ("organization_id", "brand_id", "brand_slug", "source", "source_mode", "provider"):
        op.create_index(f"ix_signals_{column}", "signals", [column])
    op.create_index("ix_signals_dedupe_key", "signals", ["dedupe_key"])
    op.create_index("ix_signals_external_id", "signals", ["external_id"])

    op.create_table(
        "classifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=False),
        sa.Column("is_about_brand", sa.Boolean(), nullable=False),
        sa.Column("area", sa.String(length=64), nullable=False),
        sa.Column("subarea", sa.String(length=64), nullable=True),
        sa.Column("sentiment", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("action_class", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("root_cause_hypothesis", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("classified_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("signal_id"),
    )
    for column in ("area", "sentiment", "severity", "action_class"):
        op.create_index(f"ix_classifications_{column}", "classifications", [column])

    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=False),
        sa.Column("classification_id", sa.Integer(), sa.ForeignKey("classifications.id"), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("destination", sa.String(length=256), nullable=True),
        sa.Column("matched_rule", sa.String(length=256), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("routed_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("signal_id"),
    )
    op.create_index("ix_routes_owner_id", "routes", ["owner_id"])

    op.create_table(
        "route_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id"), nullable=False),
        sa.Column("from_owner", sa.String(length=128), nullable=False),
        sa.Column("to_owner", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("idempotency_key"),
    )
    for column in ("route_id", "from_owner", "to_owner", "idempotency_key", "created_at"):
        op.create_index(f"ix_route_handoffs_{column}", "route_handoffs", [column])

    op.create_table(
        "feedback_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("route_id", sa.Integer(), sa.ForeignKey("routes.id"), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("actioned", sa.Boolean(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(length=128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_feedback_events_route_id", "feedback_events", ["route_id"])

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("brand_slug", sa.String(length=64), nullable=False),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("response_content", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("was_fallback", sa.Boolean(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_class", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("called_at", sa.DateTime(), nullable=False),
    )
    for column in ("organization_id", "brand_id", "brand_slug", "signal_id", "stage"):
        op.create_index(f"ix_llm_calls_{column}", "llm_calls", [column])
    op.create_index("ix_llm_calls_success", "llm_calls", ["success"])
    op.create_index("ix_llm_calls_model", "llm_calls", ["model"])
    op.create_index("ix_llm_calls_prompt_hash", "llm_calls", ["prompt_hash"])
    op.create_index("ix_llm_calls_called_at", "llm_calls", ["called_at"])

    op.create_table(
        "listening_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("brand_names", sa.JSON(), nullable=False),
        sa.Column("product_names", sa.JSON(), nullable=False),
        sa.Column("competitor_names", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("excluded_terms", sa.JSON(), nullable=False),
        sa.Column("enabled_sources", sa.JSON(), nullable=False),
        sa.Column("cadence_minutes", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=32), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("setup_notes", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "brand_id", name="uq_listening_profiles_brand"),
    )
    op.create_index("ix_listening_profiles_organization_id", "listening_profiles", ["organization_id"])
    op.create_index("ix_listening_profiles_brand_id", "listening_profiles", ["brand_id"])

    op.create_table(
        "listening_profile_suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("listening_profiles.id"), nullable=False),
        sa.Column("suggestion_type", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_listening_profile_suggestions_profile_id", "listening_profile_suggestions", ["profile_id"])
    op.create_index("ix_listening_profile_suggestions_status", "listening_profile_suggestions", ["status"])

    op.create_table(
        "listening_profile_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("listening_profiles.id"), nullable=False),
        sa.Column("field_name", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("authored_by", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_listening_profile_revisions_profile_id", "listening_profile_revisions", ["profile_id"])
    op.create_index("ix_listening_profile_revisions_field_name", "listening_profile_revisions", ["field_name"])


def downgrade() -> None:
    for table in (
        "listening_profile_revisions",
        "listening_profile_suggestions",
        "listening_profiles",
        "llm_calls",
        "feedback_events",
        "route_handoffs",
        "routes",
        "classifications",
        "signals",
        "brands",
        "memberships",
        "users",
        "teams",
        "organizations",
    ):
        op.drop_table(table)
