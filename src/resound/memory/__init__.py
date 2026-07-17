"""SQL-backed Memory. SQLite for dev, Postgres for prod — same code."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

from resound.core.memory import Memory
from resound.db import (
    configured_database_url,
    create_database_engine,
    create_session_factory,
    is_sqlite_database_url,
)
from resound.gateway import LLMGatewayError, LLMResponse
from resound.models import Classification, FeedbackEvent, RawSignal, Route
from resound.social import ListeningProfile
from resound.tenancy import TenantContext


def _sha256(text: str) -> str:
    """SHA-256 hex digest of ``text`` (utf-8). Used for ``prompt_hash`` so
    operators can run "are we sending the same prompt twice" dedup analysis
    without storing prompt text (per design decision #30)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-")


def canonical_public_platform(value: str) -> str:
    normalized = value.strip().lower()
    return "x" if normalized in {"twitter", "x_public", "x"} else normalized.removesuffix("_public")


def signal_provider_identity(
    raw: RawSignal,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return conservative canonical identity fields carried by an adapter row."""

    metadata = raw.raw_metadata or {}
    platform_value = metadata.get("canonical_platform")
    content_kind = metadata.get("content_kind")
    native_id = metadata.get("provider_native_id")
    fallback_hash = metadata.get("fallback_identity_hash")
    identity_contract_present = any(
        key in metadata
        for key in (
            "canonical_platform",
            "content_kind",
            "provider_native_id",
            "fallback_identity_hash",
        )
    )
    if not platform_value or not content_kind or bool(native_id) == bool(fallback_hash):
        if identity_contract_present:
            raise ValueError(
                "canonical provider rows require platform, content kind, and exactly one identity"
            )
        return None, None, None, None
    platform = canonical_public_platform(str(platform_value))
    return (
        platform,
        str(content_kind).strip().lower(),
        str(native_id).strip() if native_id else None,
        str(fallback_hash).strip().lower() if fallback_hash else None,
    )


def _listening_profile_payload(row: ListeningProfileRow) -> dict[str, Any]:
    return {
        "brand_names": list(row.brand_names or []),
        "product_names": list(row.product_names or []),
        "competitor_names": list(row.competitor_names or []),
        "keywords": list(row.keywords or []),
        "excluded_terms": list(row.excluded_terms or []),
        "enabled_sources": list(row.enabled_sources or []),
        "cadence_minutes": row.cadence_minutes,
        "locale": row.locale,
        "language": row.language,
        "setup_notes": row.setup_notes,
        "confidence": row.confidence,
    }


def _percentile_summary(values: list[float]) -> dict[str, float]:
    """Compute p50/p95/p99 from an unsorted list. Nearest-rank method
    (``ceil(p * n) - 1``), so a 1-element list returns that value at every
    percentile and a 2-element list returns the larger element at p95/p99.
    Empty input yields ``{"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0}``.
    """
    n = len(values)
    if n == 0:
        return {"count": 0, "p50": 0.0, "p95": 0.0, "p99": 0.0}
    s = sorted(values)
    return {
        "count": n,
        "p50": s[max(0, (n + 1) // 2 - 1)],
        "p95": s[max(0, -(-n * 95 // 100) - 1)],
        "p99": s[max(0, -(-n * 99 // 100) - 1)],
    }


class Base(DeclarativeBase):
    pass


class OrganizationRow(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class TeamRow(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_teams_org_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class MembershipRow(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "team_id", "user_id", name="uq_memberships_scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class BrandRow(Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_brands_org_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    slug: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    source_config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )


class ListeningProfileRow(Base):
    __tablename__ = "listening_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "brand_id", name="uq_listening_profiles_brand"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    brand_names: Mapped[list] = mapped_column(JSON, default=list)
    product_names: Mapped[list] = mapped_column(JSON, default=list)
    competitor_names: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    excluded_terms: Mapped[list] = mapped_column(JSON, default=list)
    enabled_sources: Mapped[list] = mapped_column(JSON, default=list)
    cadence_minutes: Mapped[int] = mapped_column(Integer, default=15)
    locale: Mapped[str | None] = mapped_column(String(32), nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="en")
    setup_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )


class ListeningProfileSuggestionRow(Base):
    __tablename__ = "listening_profile_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("listening_profiles.id"), index=True)
    suggestion_type: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class ListeningProfileRevisionRow(Base):
    __tablename__ = "listening_profile_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("listening_profiles.id"), index=True)
    field_name: Mapped[str] = mapped_column(String(64), index=True)
    old_value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | list | str | int | float | None] = mapped_column(JSON, nullable=True)
    authored_by: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SourceHealthRow(Base):
    __tablename__ = "source_health"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "brand_id",
            "canonical_source",
            "path",
            name="uq_source_health_flat_path",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64), index=True)
    canonical_source: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str] = mapped_column(String(64), default="apify", index=True)
    status: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_run_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    issues: Mapped[list] = mapped_column(JSON, default=list)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )


class AgentSessionRow(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), nullable=True, index=True)
    agent_type: Mapped[str] = mapped_column(String(64), index=True)
    user_goal: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class AgentStepRow(Base):
    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_session_id: Mapped[int] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="succeeded", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ReportConfigRow(Base):
    __tablename__ = "report_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(256))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    timeframe: Mapped[str] = mapped_column(String(32), default="7d")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )


class ReportRunRow(Base):
    __tablename__ = "report_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_config_id: Mapped[int | None] = mapped_column(
        ForeignKey("report_configs.id"), nullable=True, index=True,
    )
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    timeframe: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    source_freshness: Mapped[dict] = mapped_column(JSON, default=dict)
    sections: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    markdown: Mapped[str] = mapped_column(Text, default="")
    internal_usefulness_rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ReportCitationRow(Base):
    __tablename__ = "report_citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_run_id: Mapped[int] = mapped_column(ForeignKey("report_runs.id"), index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True, index=True,
    )
    section_title: Mapped[str] = mapped_column(String(128), index=True)
    quote: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), index=True)
    full_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WorkflowJobRow(Base):
    __tablename__ = "workflow_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    workflow_type: Mapped[str] = mapped_column(String(128), index=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True,
    )
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    task_queue: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_config_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_fingerprint_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    start_reconciliation_diagnostics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        index=True,
    )


class WorkflowLeaseRow(Base):
    __tablename__ = "workflow_leases"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "brand_id",
            "workflow_kind",
            name="uq_workflow_leases_scope",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    workflow_kind: Mapped[str] = mapped_column(String(64), index=True)
    owner_token: Mapped[str] = mapped_column(String(128), index=True)
    workflow_job_id: Mapped[int] = mapped_column(ForeignKey("workflow_jobs.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime)
    renewed_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class WorkflowEventRow(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_job_id: Mapped[int] = mapped_column(ForeignKey("workflow_jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class PublicFeedModerationEventRow(Base):
    __tablename__ = "public_feed_moderation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True,
    )
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), nullable=True, index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "(canonical_platform IS NULL AND content_kind IS NULL "
            "AND provider_native_id IS NULL AND fallback_identity_hash IS NULL) OR "
            "(organization_id IS NOT NULL AND brand_id IS NOT NULL "
            "AND canonical_platform IS NOT NULL AND content_kind IS NOT NULL "
            "AND ((provider_native_id IS NOT NULL AND fallback_identity_hash IS NULL) "
            "OR (provider_native_id IS NULL AND fallback_identity_hash IS NOT NULL)))",
            name="ck_signals_canonical_identity_complete",
        ),
        Index(
            "uq_signals_provider_native_identity",
            "organization_id",
            "brand_id",
            "canonical_platform",
            "content_kind",
            "provider_native_id",
            unique=True,
            postgresql_where=text("provider_native_id IS NOT NULL"),
            sqlite_where=text("provider_native_id IS NOT NULL"),
        ),
        Index(
            "uq_signals_fallback_identity",
            "organization_id",
            "brand_id",
            "canonical_platform",
            "content_kind",
            "fallback_identity_hash",
            unique=True,
            postgresql_where=text("fallback_identity_hash IS NOT NULL"),
            sqlite_where=text("fallback_identity_hash IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True,
    )
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), nullable=True, index=True)
    brand_slug: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_mode: Mapped[str] = mapped_column(String(32), default="public_listening", index=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    canonical_platform: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    content_kind: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    provider_native_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    fallback_identity_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(String(256), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_handle: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime)
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classification: Mapped[ClassificationRow] = relationship(
        back_populates="signal", uselist=False,
    )
    route: Mapped[RouteRow] = relationship(back_populates="signal", uselist=False)


class ClassificationRow(Base):
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), unique=True)
    is_about_brand: Mapped[bool] = mapped_column(Boolean)
    area: Mapped[str] = mapped_column(String(64), index=True)
    subarea: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sentiment: Mapped[str] = mapped_column(String(16), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    action_class: Mapped[str] = mapped_column(String(16), index=True)
    summary: Mapped[str] = mapped_column(Text)
    root_cause_hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signal: Mapped[SignalRow] = relationship(back_populates="classification")


class RouteRow(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), unique=True)
    classification_id: Mapped[int] = mapped_column(ForeignKey("classifications.id"))
    owner_id: Mapped[str] = mapped_column(String(128), index=True)
    destination: Mapped[str | None] = mapped_column(String(256), nullable=True)
    matched_rule: Mapped[str | None] = mapped_column(String(256), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    routed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    signal: Mapped[SignalRow] = relationship(back_populates="route")


class RouteHandoffRow(Base):
    """Append-only record of a routed signal moving between owners.

    The original ``routes`` row remains the router's first decision. Handoffs
    capture human team movement after that decision so the current owner can be
    projected without erasing routing history.
    """

    __tablename__ = "route_handoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    from_owner: Mapped[str] = mapped_column(String(128), index=True)
    to_owner: Mapped[str] = mapped_column(String(128), index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class FeedbackRow(Base):
    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    actioned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class LLMCallRow(Base):
    """Audit trail for every gateway invocation.

    See ``docs/design_decisions.md`` ("Task 3") for the locked schema
    rationale (decisions #26-#30). One row per ``gateway.complete()`` call
    — both success and failure paths. ``signal_id`` is nullable because
    ``memory_query`` is a corpus-level operation with no signal context.
    Failure-before-any-call rows (``LLMGatewayConfigError`` etc.) leave
    ``model``/token/cost columns null.
    """

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id"), nullable=True, index=True,
    )
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), nullable=True, index=True)
    brand_slug: Mapped[str] = mapped_column(String(64), index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True, index=True,
    )
    stage: Mapped[str] = mapped_column(String(32), index=True)
    # values: filter | classify | routing_tiebreaker | memory_query

    model: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    prompt_hash: Mapped[str] = mapped_column(String(64), index=True)
    response_content: Mapped[str | None] = mapped_column(Text, nullable=True)

    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float)

    was_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1)

    success: Mapped[bool] = mapped_column(Boolean, index=True)
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    called_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True,
    )


class SqlMemory(Memory):
    """SQL-backed Memory. Default URL: sqlite:///./data/resound.db."""

    def __init__(self, database_url: str | None = None, *, create_schema: bool | None = None):
        url = database_url or configured_database_url()
        self.engine = create_database_engine(url)
        self._session_factory = create_session_factory(self.engine)
        should_create_schema = (
            is_sqlite_database_url(url) if create_schema is None else create_schema
        )
        if should_create_schema:
            Base.metadata.create_all(self.engine)

    def session(self):
        return self._session_factory()

    # ---- tenant setup ----

    def ensure_organization(self, slug: str, display_name: str | None = None) -> int:
        normalized = _normalize_slug(slug)
        with self.session() as s:
            row = s.execute(
                select(OrganizationRow).where(OrganizationRow.slug == normalized),
            ).scalar_one_or_none()
            if row is None:
                row = OrganizationRow(slug=normalized, display_name=display_name or slug)
                s.add(row)
                s.commit()
                return row.id
            if display_name and row.display_name != display_name:
                row.display_name = display_name
                s.commit()
            return row.id

    def ensure_team(self, organization_id: int, slug: str, display_name: str | None = None) -> int:
        normalized = _normalize_slug(slug)
        with self.session() as s:
            row = s.execute(
                select(TeamRow).where(
                    TeamRow.organization_id == organization_id,
                    TeamRow.slug == normalized,
                ),
            ).scalar_one_or_none()
            if row is None:
                row = TeamRow(
                    organization_id=organization_id,
                    slug=normalized,
                    display_name=display_name or slug,
                )
                s.add(row)
                s.commit()
                return row.id
            if display_name and row.display_name != display_name:
                row.display_name = display_name
                s.commit()
            return row.id

    def ensure_user(
        self,
        external_id: str,
        display_name: str | None = None,
        email: str | None = None,
    ) -> int:
        with self.session() as s:
            row = s.execute(
                select(UserRow).where(UserRow.external_id == external_id),
            ).scalar_one_or_none()
            if row is None:
                row = UserRow(external_id=external_id, display_name=display_name, email=email)
                s.add(row)
                s.commit()
                return row.id
            if display_name:
                row.display_name = display_name
            if email:
                row.email = email
            s.commit()
            return row.id

    def ensure_membership(
        self,
        *,
        organization_id: int,
        user_id: int,
        team_id: int | None = None,
        role: str = "member",
    ) -> int:
        with self.session() as s:
            row = s.execute(
                select(MembershipRow).where(
                    MembershipRow.organization_id == organization_id,
                    MembershipRow.team_id == team_id,
                    MembershipRow.user_id == user_id,
                ),
            ).scalar_one_or_none()
            if row is None:
                row = MembershipRow(
                    organization_id=organization_id,
                    team_id=team_id,
                    user_id=user_id,
                    role=role,
                )
                s.add(row)
                s.commit()
                return row.id
            if row.role != role:
                row.role = role
                s.commit()
            return row.id

    def ensure_brand(
        self,
        organization_id: int,
        slug: str,
        display_name: str | None = None,
        *,
        description: str = "",
        source_config: dict | None = None,
    ) -> BrandRow:
        normalized = _normalize_slug(slug)
        with self.session() as s:
            row = s.execute(
                select(BrandRow).where(
                    BrandRow.organization_id == organization_id,
                    BrandRow.slug == normalized,
                ),
            ).scalar_one_or_none()
            if row is None:
                row = BrandRow(
                    organization_id=organization_id,
                    slug=normalized,
                    display_name=display_name or slug,
                    description=description,
                    source_config=source_config or {},
                )
                s.add(row)
                s.commit()
                return row
            if display_name:
                row.display_name = display_name
            row.description = description if description else row.description
            if source_config is not None:
                row.source_config = source_config
            s.commit()
            return row

    def list_brands_for_tenant(self, context: TenantContext) -> list[BrandRow]:
        with self.session() as s:
            stmt = (
                select(BrandRow)
                .where(BrandRow.organization_id == context.organization_id)
                .order_by(BrandRow.display_name, BrandRow.id)
            )
            return list(s.execute(stmt).scalars())

    def list_signals_for_tenant(
        self,
        context: TenantContext,
        *,
        brand_slug: str | None = None,
    ) -> list[SignalRow]:
        with self.session() as s:
            stmt = (
                select(SignalRow)
                .where(SignalRow.organization_id == context.organization_id)
                .order_by(SignalRow.ingested_at.desc(), SignalRow.id.desc())
            )
            if brand_slug:
                stmt = stmt.where(SignalRow.brand_slug == brand_slug)
            return list(s.execute(stmt).scalars())

    def save_listening_profile(
        self,
        *,
        organization_id: int,
        brand_id: int,
        profile: ListeningProfile,
        authored_by: str = "user",
    ) -> int:
        with self.session() as s:
            row = s.execute(
                select(ListeningProfileRow).where(
                    ListeningProfileRow.organization_id == organization_id,
                    ListeningProfileRow.brand_id == brand_id,
                ),
            ).scalar_one_or_none()
            payload = {
                "brand_names": profile.brand_names,
                "product_names": profile.product_names,
                "competitor_names": profile.competitor_names,
                "keywords": profile.keywords,
                "excluded_terms": profile.excluded_terms,
                "enabled_sources": list(profile.enabled_sources),
                "cadence_minutes": profile.cadence_minutes,
                "locale": profile.locale,
                "language": profile.language,
                "setup_notes": profile.setup_notes,
                "confidence": profile.confidence,
            }
            if row is None:
                row = ListeningProfileRow(
                    organization_id=organization_id,
                    brand_id=brand_id,
                    **payload,
                )
                s.add(row)
                s.commit()
                return row.id

            before = _listening_profile_payload(row)
            for key, value in payload.items():
                setattr(row, key, value)
            s.commit()
            for key, old_value in before.items():
                new_value = payload[key]
                if old_value == new_value:
                    continue
                revision = ListeningProfileRevisionRow(
                    profile_id=row.id,
                    field_name=key,
                    old_value=old_value,
                    new_value=new_value,
                    authored_by=authored_by,
                )
                s.add(revision)
            s.commit()
            return row.id

    def get_listening_profile(
        self,
        *,
        organization_id: int,
        brand_id: int,
        brand_slug: str,
    ) -> ListeningProfile | None:
        with self.session() as s:
            row = s.execute(
                select(ListeningProfileRow).where(
                    ListeningProfileRow.organization_id == organization_id,
                    ListeningProfileRow.brand_id == brand_id,
                ),
            ).scalar_one_or_none()
            if row is None:
                return None
            brand = s.execute(
                select(BrandRow).where(
                    BrandRow.organization_id == organization_id,
                    BrandRow.id == brand_id,
                ),
            ).scalar_one_or_none()
            return ListeningProfile(
                brand_slug=brand_slug,
                brand_names=list(row.brand_names or []),
                product_names=list(row.product_names or []),
                competitor_names=list(row.competitor_names or []),
                keywords=list(row.keywords or []),
                excluded_terms=list(row.excluded_terms or []),
                enabled_sources=list(row.enabled_sources or []),
                cadence_minutes=row.cadence_minutes,
                locale=row.locale,
                language=row.language,
                setup_notes=row.setup_notes,
                confidence=row.confidence,
                source_config=dict(brand.source_config or {}) if brand is not None else {},
            )

    def create_listening_profile_suggestion(
        self,
        *,
        profile_id: int,
        suggestion_type: str,
        value: str,
        reason: str | None = None,
        status: str = "pending",
    ) -> int:
        with self.session() as s:
            row = ListeningProfileSuggestionRow(
                profile_id=profile_id,
                suggestion_type=suggestion_type,
                value=value,
                reason=reason,
                status=status,
            )
            s.add(row)
            s.commit()
            return row.id

    def list_listening_profile_suggestions(
        self,
        profile_id: int,
    ) -> list[ListeningProfileSuggestionRow]:
        with self.session() as s:
            stmt = (
                select(ListeningProfileSuggestionRow)
                .where(ListeningProfileSuggestionRow.profile_id == profile_id)
                .order_by(
                    ListeningProfileSuggestionRow.created_at,
                    ListeningProfileSuggestionRow.id,
                )
            )
            return list(s.execute(stmt).scalars())

    def list_listening_profile_revisions(
        self,
        profile_id: int,
    ) -> list[ListeningProfileRevisionRow]:
        with self.session() as s:
            stmt = (
                select(ListeningProfileRevisionRow)
                .where(ListeningProfileRevisionRow.profile_id == profile_id)
                .order_by(ListeningProfileRevisionRow.created_at, ListeningProfileRevisionRow.id)
            )
            return list(s.execute(stmt).scalars())

    def apply_listening_profile_suggestion_decision(
        self,
        *,
        suggestion_id: int,
        organization_id: int,
        decision: str,
        edited_value: str | None = None,
        authored_by: str = "user",
    ) -> ListeningProfileSuggestionRow | None:
        field_by_type = {
            "brand": "brand_names",
            "product": "product_names",
            "competitor": "competitor_names",
            "keyword": "keywords",
            "excluded_term": "excluded_terms",
            "source": "enabled_sources",
        }
        with self.session() as s:
            suggestion = s.execute(
                select(ListeningProfileSuggestionRow).where(
                    ListeningProfileSuggestionRow.id == suggestion_id,
                ),
            ).scalar_one_or_none()
            if suggestion is None:
                return None
            profile = s.execute(
                select(ListeningProfileRow).where(
                    ListeningProfileRow.id == suggestion.profile_id,
                    ListeningProfileRow.organization_id == organization_id,
                ),
            ).scalar_one_or_none()
            if profile is None:
                return None

            if decision not in {"accept", "edit", "reject"}:
                raise ValueError(f"Unsupported listening profile suggestion decision: {decision}")
            if decision == "edit" and not (edited_value or "").strip():
                raise ValueError("edited_value is required when editing a suggestion")

            suggestion.status = "rejected" if decision == "reject" else f"{decision}ed"
            suggestion.resolved_at = datetime.utcnow()
            if decision == "reject":
                s.commit()
                return suggestion

            field_name = field_by_type.get(suggestion.suggestion_type)
            if field_name is None:
                raise ValueError(
                    "Unsupported listening profile suggestion type: "
                    f"{suggestion.suggestion_type}"
                )
            old_value = list(getattr(profile, field_name) or [])
            value = (edited_value if decision == "edit" else suggestion.value).strip()
            new_value = [*old_value]
            if value and value not in new_value:
                new_value.append(value)
            setattr(profile, field_name, new_value)
            if old_value != new_value:
                s.add(
                    ListeningProfileRevisionRow(
                        profile_id=profile.id,
                        field_name=field_name,
                        old_value=old_value,
                        new_value=new_value,
                        authored_by=authored_by,
                    )
                )
            s.commit()
            return suggestion

    def record_source_health(
        self,
        *,
        organization_id: int,
        brand_id: int,
        source_type: str,
        provider: str,
        canonical_source: str | None = None,
        path: str = "official_discovery",
        status: str,
        run_id: str | None = None,
        item_count: int = 0,
        fetched_count: int | None = None,
        processed_count: int | None = None,
        duplicate_count: int = 0,
        cost_usd: Decimal | float = 0,
        provenance: dict[str, Any] | None = None,
        issues: list[dict[str, Any]] | None = None,
        error_message: str | None = None,
        checked_at: datetime | None = None,
    ) -> int:
        checked_at = checked_at or datetime.utcnow()
        canonical_source = canonical_public_platform(canonical_source or source_type)
        if path not in {
            "official_discovery",
            "mention_discovery",
            "official_comments",
            "mention_comments",
        }:
            raise ValueError(f"Unsupported public-listening path: {path}")
        if canonical_source in {"reddit", "x", "youtube"} and path.endswith("comments"):
            raise ValueError(f"{canonical_source} does not support comment health paths")
        with self.session() as s:
            row = s.execute(
                select(SourceHealthRow).where(
                    SourceHealthRow.organization_id == organization_id,
                    SourceHealthRow.brand_id == brand_id,
                    SourceHealthRow.canonical_source == canonical_source,
                    SourceHealthRow.path == path,
                ),
            ).scalar_one_or_none()
            if row is None:
                row = SourceHealthRow(
                    organization_id=organization_id,
                    brand_id=brand_id,
                    source_type=source_type,
                    canonical_source=canonical_source,
                    path=path,
                    provider=provider,
                )
                s.add(row)
            row.status = status
            row.provider = provider
            row.last_run_id = run_id
            row.item_count = item_count
            row.fetched_count = item_count if fetched_count is None else fetched_count
            row.processed_count = item_count if processed_count is None else processed_count
            row.duplicate_count = duplicate_count
            row.cost_usd = float(cost_usd)
            row.provenance = provenance or {}
            row.issues = issues or []
            row.error_message = error_message
            if status == "ok":
                row.last_success_at = checked_at
            else:
                row.last_failure_at = checked_at
            s.commit()
            return row.id

    def list_source_health(self, organization_id: int, brand_id: int) -> list[SourceHealthRow]:
        with self.session() as s:
            stmt = (
                select(SourceHealthRow)
                .where(
                    SourceHealthRow.organization_id == organization_id,
                    SourceHealthRow.brand_id == brand_id,
                )
                .order_by(SourceHealthRow.canonical_source, SourceHealthRow.path)
            )
            return list(s.execute(stmt).scalars())

    def count_report_runs_by_status(
        self,
        *,
        organization_id: int,
        brand_id: int | None = None,
    ) -> dict[str, int]:
        with self.session() as s:
            stmt = (
                select(ReportRunRow.status, func.count(ReportRunRow.id))
                .where(ReportRunRow.organization_id == organization_id)
                .group_by(ReportRunRow.status)
            )
            if brand_id is not None:
                stmt = stmt.where(ReportRunRow.brand_id == brand_id)
            return {status: int(count) for status, count in s.execute(stmt).all()}

    # ---- agent/report artifacts ----

    def create_agent_session(
        self,
        *,
        organization_id: int,
        brand_id: int | None,
        agent_type: str,
        user_goal: str,
        status: str = "running",
    ) -> int:
        with self.session() as s:
            row = AgentSessionRow(
                organization_id=organization_id,
                brand_id=brand_id,
                agent_type=agent_type,
                user_goal=user_goal,
                status=status,
            )
            s.add(row)
            s.commit()
            return row.id

    def record_agent_step(
        self,
        *,
        agent_session_id: int,
        tool_name: str,
        input_json: dict | None = None,
        output_json: dict | None = None,
        status: str = "succeeded",
        error_message: str | None = None,
    ) -> int:
        with self.session() as s:
            row = AgentStepRow(
                agent_session_id=agent_session_id,
                tool_name=tool_name,
                input_json=input_json or {},
                output_json=output_json or {},
                status=status,
                error_message=error_message,
            )
            s.add(row)
            s.commit()
            return row.id

    def update_agent_session_status(self, agent_session_id: int, status: str) -> None:
        with self.session() as s:
            row = s.execute(
                select(AgentSessionRow).where(AgentSessionRow.id == agent_session_id),
            ).scalar_one_or_none()
            if row is None:
                return
            row.status = status
            if status in {"completed", "failed", "waiting_for_approval"}:
                row.completed_at = datetime.utcnow()
            s.commit()

    def list_agent_steps(self, agent_session_id: int) -> list[AgentStepRow]:
        with self.session() as s:
            stmt = (
                select(AgentStepRow)
                .where(AgentStepRow.agent_session_id == agent_session_id)
                .order_by(AgentStepRow.created_at, AgentStepRow.id)
            )
            return list(s.execute(stmt).scalars())

    def list_agent_sessions_for_tenant(self, context: TenantContext) -> list[AgentSessionRow]:
        with self.session() as s:
            stmt = (
                select(AgentSessionRow)
                .where(AgentSessionRow.organization_id == context.organization_id)
                .order_by(AgentSessionRow.created_at.desc(), AgentSessionRow.id.desc())
            )
            return list(s.execute(stmt).scalars())

    def save_report_config(
        self,
        *,
        organization_id: int,
        brand_id: int,
        team_id: int | None,
        role: str,
        name: str,
        filters: dict | None = None,
        timeframe: str = "7d",
    ) -> int:
        with self.session() as s:
            row = ReportConfigRow(
                organization_id=organization_id,
                brand_id=brand_id,
                team_id=team_id,
                role=role,
                name=name,
                filters=filters or {},
                timeframe=timeframe,
            )
            s.add(row)
            s.commit()
            return row.id

    def get_report_config(self, report_config_id: int) -> ReportConfigRow | None:
        with self.session() as s:
            return s.execute(
                select(ReportConfigRow).where(ReportConfigRow.id == report_config_id),
            ).scalar_one_or_none()

    def create_report_run(
        self,
        *,
        organization_id: int,
        brand_id: int,
        team_id: int | None,
        role: str,
        timeframe: str,
        status: str,
        report_config_id: int | None = None,
        source_freshness: dict | None = None,
        sections: list | None = None,
        summary: str = "",
        markdown: str = "",
        internal_usefulness_rating: float | None = None,
    ) -> int:
        with self.session() as s:
            row = ReportRunRow(
                report_config_id=report_config_id,
                organization_id=organization_id,
                brand_id=brand_id,
                team_id=team_id,
                role=role,
                timeframe=timeframe,
                status=status,
                source_freshness=source_freshness or {},
                sections=sections or [],
                summary=summary,
                markdown=markdown,
                internal_usefulness_rating=internal_usefulness_rating,
            )
            s.add(row)
            s.commit()
            return row.id

    def get_report_run(self, report_run_id: int) -> ReportRunRow | None:
        with self.session() as s:
            return s.execute(
                select(ReportRunRow).where(ReportRunRow.id == report_run_id),
            ).scalar_one_or_none()

    def list_report_runs_for_tenant(self, context: TenantContext) -> list[ReportRunRow]:
        with self.session() as s:
            stmt = (
                select(ReportRunRow)
                .where(ReportRunRow.organization_id == context.organization_id)
                .order_by(ReportRunRow.generated_at.desc(), ReportRunRow.id.desc())
            )
            return list(s.execute(stmt).scalars())

    def save_report_citation(
        self,
        *,
        report_run_id: int,
        signal_id: int | None,
        section_title: str,
        quote: str,
        source: str,
        full_text: str,
    ) -> int:
        with self.session() as s:
            row = ReportCitationRow(
                report_run_id=report_run_id,
                signal_id=signal_id,
                section_title=section_title,
                quote=quote,
                source=source,
                full_text=full_text,
            )
            s.add(row)
            s.commit()
            return row.id

    def list_report_citations(self, report_run_id: int) -> list[ReportCitationRow]:
        with self.session() as s:
            stmt = (
                select(ReportCitationRow)
                .where(ReportCitationRow.report_run_id == report_run_id)
                .order_by(ReportCitationRow.id)
            )
            return list(s.execute(stmt).scalars())

    def create_workflow_job(
        self,
        *,
        workflow_id: str,
        run_id: str | None = None,
        workflow_type: str,
        organization_id: int | None,
        brand_id: int | None,
        status: str = "queued",
        task_queue: str | None = None,
        resolved_config_snapshot: dict | None = None,
        request_fingerprint_summary: dict | None = None,
    ) -> int:
        if resolved_config_snapshot is not None:
            from resound.workflows.result_persistence import bounded_request_snapshot

            resolved_config_snapshot = bounded_request_snapshot(resolved_config_snapshot)
        with self.session() as s:
            row = WorkflowJobRow(
                workflow_id=workflow_id,
                run_id=run_id,
                workflow_type=workflow_type,
                organization_id=organization_id,
                brand_id=brand_id,
                status=status,
                task_queue=task_queue,
                resolved_config_snapshot=resolved_config_snapshot,
                request_fingerprint_summary=request_fingerprint_summary,
            )
            s.add(row)
            s.commit()
            return row.id

    def acquire_workflow_lease(
        self,
        *,
        organization_id: int,
        brand_id: int,
        workflow_job_id: int,
        workflow_kind: str = "public_listening_sync",
        owner_token: str | None = None,
        ttl_seconds: int = 120,
        now: datetime | None = None,
    ) -> WorkflowLeaseRow | None:
        """Acquire or take over an expired brand-scoped workflow lease."""

        owner_token = owner_token or secrets.token_urlsafe(32)
        with self.session() as s:
            database_now = now or s.execute(select(func.current_timestamp())).scalar_one()
            expires_at = database_now + timedelta(seconds=ttl_seconds)
            row = WorkflowLeaseRow(
                organization_id=organization_id,
                brand_id=brand_id,
                workflow_kind=workflow_kind,
                owner_token=owner_token,
                workflow_job_id=workflow_job_id,
                status="active",
                acquired_at=database_now,
                renewed_at=database_now,
                expires_at=expires_at,
            )
            try:
                with s.begin_nested():
                    s.add(row)
                    s.flush()
                s.commit()
                return row
            except IntegrityError:
                s.rollback()

            result = s.execute(
                update(WorkflowLeaseRow)
                .where(
                    WorkflowLeaseRow.organization_id == organization_id,
                    WorkflowLeaseRow.brand_id == brand_id,
                    WorkflowLeaseRow.workflow_kind == workflow_kind,
                    WorkflowLeaseRow.expires_at <= database_now,
                )
                .values(
                    owner_token=owner_token,
                    workflow_job_id=workflow_job_id,
                    status="active",
                    acquired_at=database_now,
                    renewed_at=database_now,
                    expires_at=expires_at,
                )
            )
            if result.rowcount != 1:
                s.rollback()
                return None
            s.commit()
            return s.execute(
                select(WorkflowLeaseRow).where(
                    WorkflowLeaseRow.organization_id == organization_id,
                    WorkflowLeaseRow.brand_id == brand_id,
                    WorkflowLeaseRow.workflow_kind == workflow_kind,
                )
            ).scalar_one()

    def renew_workflow_lease(
        self,
        *,
        organization_id: int,
        brand_id: int,
        owner_token: str,
        workflow_kind: str = "public_listening_sync",
        ttl_seconds: int = 120,
        now: datetime | None = None,
    ) -> bool:
        with self.session() as s:
            database_now = now or s.execute(select(func.current_timestamp())).scalar_one()
            result = s.execute(
                update(WorkflowLeaseRow)
                .where(
                    WorkflowLeaseRow.organization_id == organization_id,
                    WorkflowLeaseRow.brand_id == brand_id,
                    WorkflowLeaseRow.workflow_kind == workflow_kind,
                    WorkflowLeaseRow.owner_token == owner_token,
                    WorkflowLeaseRow.status == "active",
                    WorkflowLeaseRow.expires_at > database_now,
                )
                .values(
                    renewed_at=database_now,
                    expires_at=database_now + timedelta(seconds=ttl_seconds),
                )
            )
            s.commit()
            return result.rowcount == 1

    def finalize_workflow_job(
        self,
        *,
        workflow_job_id: int,
        organization_id: int,
        brand_id: int,
        owner_token: str,
        status: str,
        result_summary: dict,
        result_schema_version: int = 1,
        workflow_kind: str = "public_listening_sync",
        now: datetime | None = None,
    ) -> bool:
        """Persist terminal state and release only the owning lease atomically."""

        from resound.workflows.result_persistence import bounded_result_summary

        result_summary = bounded_result_summary(result_summary)
        with self.session() as s:
            database_now = now or s.execute(select(func.current_timestamp())).scalar_one()
            lease = s.execute(
                select(WorkflowLeaseRow).where(
                    WorkflowLeaseRow.organization_id == organization_id,
                    WorkflowLeaseRow.brand_id == brand_id,
                    WorkflowLeaseRow.workflow_kind == workflow_kind,
                    WorkflowLeaseRow.owner_token == owner_token,
                    WorkflowLeaseRow.workflow_job_id == workflow_job_id,
                    WorkflowLeaseRow.status == "active",
                )
            ).scalar_one_or_none()
            if lease is None:
                return False
            job = s.get(WorkflowJobRow, workflow_job_id)
            if job is None:
                return False
            job.status = status
            job.result_schema_version = result_schema_version
            job.result_summary = result_summary
            lease.status = status
            lease.renewed_at = database_now
            lease.expires_at = database_now
            s.commit()
            return True

    def get_workflow_job(self, workflow_id: str) -> WorkflowJobRow | None:
        with self.session() as s:
            return s.execute(
                select(WorkflowJobRow).where(WorkflowJobRow.workflow_id == workflow_id),
            ).scalar_one_or_none()

    def update_workflow_job_handle(
        self,
        *,
        workflow_id: str,
        run_id: str | None,
        task_queue: str | None,
        status: str = "queued",
    ) -> None:
        with self.session() as s:
            row = s.execute(
                select(WorkflowJobRow).where(WorkflowJobRow.workflow_id == workflow_id),
            ).scalar_one_or_none()
            if row is None:
                return
            row.run_id = run_id
            row.task_queue = task_queue
            row.status = status
            s.commit()

    def record_workflow_event(
        self,
        *,
        workflow_job_id: int,
        stage: str,
        status: str,
        message: str | None = None,
        event_metadata: dict | None = None,
    ) -> int:
        with self.session() as s:
            row = WorkflowEventRow(
                workflow_job_id=workflow_job_id,
                stage=stage,
                status=status,
                message=message,
                event_metadata=event_metadata or {},
            )
            s.add(row)
            s.commit()
            return row.id

    def list_workflow_events(self, workflow_job_id: int) -> list[WorkflowEventRow]:
        with self.session() as s:
            stmt = (
                select(WorkflowEventRow)
                .where(WorkflowEventRow.workflow_job_id == workflow_job_id)
                .order_by(WorkflowEventRow.created_at, WorkflowEventRow.id)
            )
            return list(s.execute(stmt).scalars())

    def list_public_feed_items(self, brand_slug: str, limit: int) -> list[SignalRow]:
        with self.session() as s:
            stmt = (
                select(SignalRow)
                .where(SignalRow.brand_slug == brand_slug)
                .order_by(SignalRow.posted_at.desc(), SignalRow.id.desc())
            )
            rows = list(s.execute(stmt).scalars())
            visible = [
                row for row in rows
                if (row.raw_metadata or {}).get("public_feed_visible") is True
                and (row.raw_metadata or {}).get("public_feed_takedown") is not True
            ]
            return visible[:max(1, min(limit, 50))]

    def moderate_public_feed_item(
        self,
        *,
        signal_id: int,
        organization_id: int,
        action: str,
        reason: str | None = None,
        actor: str | None = None,
    ) -> PublicFeedModerationEventRow | None:
        with self.session() as s:
            signal = s.execute(
                select(SignalRow).where(
                    SignalRow.id == signal_id,
                    SignalRow.organization_id == organization_id,
                ),
            ).scalar_one_or_none()
            if signal is None:
                return None
            metadata = dict(signal.raw_metadata or {})
            if action == "show":
                metadata["public_feed_visible"] = True
                metadata["public_feed_takedown"] = False
            elif action == "hide":
                metadata["public_feed_visible"] = False
            elif action == "takedown":
                metadata["public_feed_visible"] = False
                metadata["public_feed_takedown"] = True
            elif action == "no_export":
                metadata["public_feed_no_export"] = True
            else:
                raise ValueError(f"Unsupported public feed moderation action: {action}")
            signal.raw_metadata = metadata
            event = PublicFeedModerationEventRow(
                organization_id=signal.organization_id,
                brand_id=signal.brand_id,
                signal_id=signal.id,
                action=action,
                reason=reason,
                actor=actor,
            )
            s.add(event)
            s.commit()
            return event

    def list_public_feed_moderation_events(
        self,
        signal_id: int,
    ) -> list[PublicFeedModerationEventRow]:
        with self.session() as s:
            stmt = (
                select(PublicFeedModerationEventRow)
                .where(PublicFeedModerationEventRow.signal_id == signal_id)
                .order_by(PublicFeedModerationEventRow.created_at, PublicFeedModerationEventRow.id)
            )
            return list(s.execute(stmt).scalars())

    # ---- writes ----

    def signal_dedupe_key(
        self,
        brand_slug: str,
        raw: RawSignal,
        *,
        organization_id: int | None = None,
        brand_id: int | None = None,
    ) -> str:
        base = raw.dedupe_key()
        if organization_id is None:
            return base
        brand_scope = brand_id if brand_id is not None else brand_slug
        return f"org:{organization_id}::brand:{brand_scope}::{base}"

    def has_seen(self, dedupe_key: str) -> bool:
        with Session(self.engine) as s:
            stmt = select(SignalRow.id).where(SignalRow.dedupe_key == dedupe_key)
            return s.execute(stmt).first() is not None

    def record_signal(
        self,
        brand_slug: str,
        raw: RawSignal,
        *,
        organization_id: int | None = None,
        brand_id: int | None = None,
    ) -> int:
        canonical_platform, content_kind, native_id, fallback_hash = signal_provider_identity(raw)
        with self.session() as s:
            row = SignalRow(
                organization_id=organization_id,
                brand_id=brand_id,
                brand_slug=brand_slug,
                source=raw.source,
                source_mode=raw.source_mode,
                provider=raw.provider,
                canonical_platform=canonical_platform,
                content_kind=content_kind,
                provider_native_id=native_id,
                fallback_identity_hash=fallback_hash,
                external_id=raw.external_id,
                dedupe_key=self.signal_dedupe_key(
                    brand_slug,
                    raw,
                    organization_id=organization_id,
                    brand_id=brand_id,
                ),
                url=raw.url,
                author_handle=raw.author_handle,
                content=raw.content,
                posted_at=raw.posted_at,
                raw_metadata=raw.raw_metadata,
            )
            try:
                with s.begin_nested():
                    s.add(row)
                    s.flush()
                s.commit()
                return row.id
            except IntegrityError:
                s.rollback()
                identity_filters = [
                    SignalRow.organization_id == organization_id,
                    SignalRow.brand_id == brand_id,
                    SignalRow.canonical_platform == canonical_platform,
                    SignalRow.content_kind == content_kind,
                ]
                if native_id:
                    identity_filters.append(SignalRow.provider_native_id == native_id)
                elif fallback_hash:
                    identity_filters.append(SignalRow.fallback_identity_hash == fallback_hash)
                else:
                    identity_filters = [SignalRow.dedupe_key == row.dedupe_key]
                existing = s.execute(
                    select(SignalRow.id).where(*identity_filters)
                ).scalar_one_or_none()
                if existing is None:
                    raise
                return existing

    def load_classification(self, signal_id: int) -> tuple[int, Classification] | None:
        with self.session() as s:
            row = s.execute(
                select(ClassificationRow).where(ClassificationRow.signal_id == signal_id)
            ).scalar_one_or_none()
            if row is None:
                return None
            return row.id, Classification(
                is_about_brand=row.is_about_brand,
                area=row.area,
                subarea=row.subarea,
                sentiment=row.sentiment,
                severity=row.severity,
                action_class=row.action_class,
                summary=row.summary,
                root_cause_hypothesis=row.root_cause_hypothesis,
                confidence=row.confidence,
                reasoning=row.reasoning,
            )

    def record_classification(self, signal_id: int, classification: Classification) -> int:
        with Session(self.engine) as s:
            row = ClassificationRow(
                signal_id=signal_id,
                is_about_brand=classification.is_about_brand,
                area=classification.area,
                subarea=classification.subarea,
                sentiment=classification.sentiment.value,
                severity=classification.severity.value,
                action_class=classification.action_class.value,
                summary=classification.summary,
                root_cause_hypothesis=classification.root_cause_hypothesis,
                confidence=classification.confidence,
                reasoning=classification.reasoning,
            )
            try:
                with s.begin_nested():
                    s.add(row)
                    s.flush()
                s.commit()
                return row.id
            except IntegrityError:
                s.rollback()
                return s.execute(
                    select(ClassificationRow.id).where(ClassificationRow.signal_id == signal_id)
                ).scalar_one()

    def record_route(self, signal_id: int, classification_id: int, route: Route) -> int:
        with Session(self.engine) as s:
            row = RouteRow(
                signal_id=signal_id,
                classification_id=classification_id,
                owner_id=route.owner_id,
                destination=route.destination,
                matched_rule=route.matched_rule,
                priority=route.priority,
                notes=route.notes,
            )
            try:
                with s.begin_nested():
                    s.add(row)
                    s.flush()
                s.commit()
                return row.id
            except IntegrityError:
                s.rollback()
                return s.execute(
                    select(RouteRow.id).where(RouteRow.signal_id == signal_id)
                ).scalar_one()

    def record_feedback(self, event: FeedbackEvent) -> int:
        with Session(self.engine) as s:
            row = FeedbackRow(
                route_id=event.route_id,
                correct=event.correct,
                actioned=event.actioned,
                note=event.note,
                submitted_by=event.submitted_by,
                submitted_at=event.submitted_at,
            )
            s.add(row)
            s.commit()
            return row.id

    def record_route_handoff(
        self,
        *,
        route_id: int,
        from_owner: str,
        to_owner: str,
        note: str | None = None,
        submitted_by: str | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        """Append a human handoff for a route and return the event id.

        ``idempotency_key`` is optional for local/dev use, but API callers should
        provide it so mobile retries don't create duplicate handoffs.
        """
        with Session(self.engine) as s:
            if idempotency_key:
                existing = s.execute(
                    select(RouteHandoffRow.id).where(
                        RouteHandoffRow.idempotency_key == idempotency_key,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    return existing

            row = RouteHandoffRow(
                route_id=route_id,
                from_owner=from_owner,
                to_owner=to_owner,
                note=note,
                submitted_by=submitted_by,
                idempotency_key=idempotency_key,
            )
            s.add(row)
            s.commit()
            return row.id

    def record_llm_call(
        self,
        *,
        brand_slug: str,
        stage: str,
        prompt: str,
        response: LLMResponse,
        was_fallback: bool,
        attempt_count: int,
        signal_id: int | None = None,
        organization_id: int | None = None,
        brand_id: int | None = None,
    ) -> int:
        """Record a successful LLM gateway call to the audit trail.

        Split from :meth:`record_llm_failure` per design decision #28 — the
        success path always has an :class:`LLMResponse`, the failure path
        never does. ``was_fallback`` and ``attempt_count`` are repeated as
        explicit args (also on ``response``) so call sites are self-documenting
        and tests don't have to construct an ``LLMResponse`` to assert intent.
        """
        with Session(self.engine) as s:
            row = LLMCallRow(
                organization_id=organization_id,
                brand_id=brand_id,
                brand_slug=brand_slug,
                signal_id=signal_id,
                stage=stage,
                model=response.model_used,
                prompt_hash=_sha256(prompt),
                response_content=response.content,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
                cost_usd=response.cost_usd,
                latency_ms=response.latency_ms,
                was_fallback=was_fallback,
                attempt_count=attempt_count,
                success=True,
                error_class=None,
                error_message=None,
            )
            s.add(row)
            s.commit()
            return row.id

    def record_llm_failure(
        self,
        *,
        brand_slug: str,
        stage: str,
        prompt: str,
        error: LLMGatewayError,
        latency_ms: float,
        attempt_count: int,
        signal_id: int | None = None,
        organization_id: int | None = None,
        brand_id: int | None = None,
    ) -> int:
        """Record a failed LLM gateway call to the audit trail.

        Failure-path companion to :meth:`record_llm_call`. Usage from billable
        malformed responses is retained when the gateway provides it; fields
        remain null for failures that never reached or returned from a model.
        ``error.__class__.__name__`` is stored
        in ``error_class`` so dashboards can group failures by type without
        substring-matching the message.
        """
        with Session(self.engine) as s:
            row = LLMCallRow(
                organization_id=organization_id,
                brand_id=brand_id,
                brand_slug=brand_slug,
                signal_id=signal_id,
                stage=stage,
                model=getattr(error, "model_used", None),
                prompt_hash=_sha256(prompt),
                response_content=None,
                tokens_in=getattr(error, "tokens_in", None),
                tokens_out=getattr(error, "tokens_out", None),
                cost_usd=getattr(error, "cost_usd", None),
                latency_ms=getattr(error, "latency_ms", 0.0) or latency_ms,
                was_fallback=False,
                attempt_count=attempt_count,
                success=False,
                error_class=type(error).__name__,
                error_message=str(error),
            )
            s.add(row)
            s.commit()
            return row.id

    # ---- reads ----

    def query_recent(self, brand_slug: str, limit: int = 50) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            stmt = (
                select(SignalRow)
                .where(SignalRow.brand_slug == brand_slug)
                .order_by(SignalRow.ingested_at.desc())
                .limit(limit)
            )
            results = []
            for sig in s.execute(stmt).scalars():
                results.append(
                    {
                        "signal_id": sig.id,
                        "source": sig.source,
                        "url": sig.url,
                        "author": sig.author_handle,
                        "content": sig.content,
                        "posted_at": sig.posted_at,
                        "ingested_at": sig.ingested_at,
                        "area": sig.classification.area if sig.classification else None,
                        "sentiment": sig.classification.sentiment if sig.classification else None,
                        "severity": sig.classification.severity if sig.classification else None,
                        "action_class": (
                            sig.classification.action_class if sig.classification else None
                        ),
                        "summary": sig.classification.summary if sig.classification else None,
                        "owner": sig.route.owner_id if sig.route else None,
                        "destination": sig.route.destination if sig.route else None,
                    }
                )
            return results

    # ---- LLM telemetry reads ----

    def query_llm_costs(
        self,
        brand_slug: str,
        since: datetime,
        organization_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate LLM spend by ``(stage, model)`` for ``brand_slug`` since
        ``since``. Successful calls and failed calls with known billable usage
        are included; failures without provider-reported cost remain excluded.

        Returns a list of dicts, one per ``(stage, model)`` group:
        ``{"stage": str, "model": str, "call_count": int,
        "total_cost_usd": float, "total_tokens_in": int,
        "total_tokens_out": int}``. Rows where ``cost_usd`` is NULL still
        appear in ``call_count`` but contribute 0 to ``total_cost_usd``
        (per design decision #7 — OpenRouter sometimes omits ``usage.cost``).
        """
        with Session(self.engine) as s:
            stmt = (
                select(
                    LLMCallRow.stage,
                    LLMCallRow.model,
                    func.count(LLMCallRow.id).label("call_count"),
                    func.coalesce(func.sum(LLMCallRow.cost_usd), 0.0).label(
                        "total_cost_usd"
                    ),
                    func.coalesce(func.sum(LLMCallRow.tokens_in), 0).label(
                        "total_tokens_in"
                    ),
                    func.coalesce(func.sum(LLMCallRow.tokens_out), 0).label(
                        "total_tokens_out"
                    ),
                )
                .where(LLMCallRow.brand_slug == brand_slug)
                .where(LLMCallRow.called_at >= since)
                .where(
                    (LLMCallRow.success.is_(True))
                    | (LLMCallRow.cost_usd.is_not(None))
                )
                .group_by(LLMCallRow.stage, LLMCallRow.model)
                .order_by(LLMCallRow.stage, LLMCallRow.model)
            )
            if organization_id is not None:
                stmt = stmt.where(LLMCallRow.organization_id == organization_id)
            return [
                {
                    "stage": stage,
                    "model": model,
                    "call_count": call_count,
                    "total_cost_usd": float(total_cost_usd),
                    "total_tokens_in": int(total_tokens_in),
                    "total_tokens_out": int(total_tokens_out),
                }
                for stage, model, call_count, total_cost_usd,
                total_tokens_in, total_tokens_out in s.execute(stmt).all()
            ]

    def query_llm_latency(
        self,
        brand_slug: str,
        since: datetime,
        organization_id: int | None = None,
    ) -> dict[str, dict[str, float]]:
        """Compute p50/p95/p99 latency per stage for ``brand_slug`` since
        ``since``. Excludes failure rows (per design #32 — timeout-capped
        outliers would skew p95 toward the wall-clock cap).

        Returns ``{stage: {"p50": float, "p95": float, "p99": float,
        "count": int}}`` (latency in milliseconds). Stages with no
        successful calls in the window are absent from the result.

        **Implementation note:** percentiles are computed Python-side
        (sort + slice) for SQLite portability — see decision #32. For
        production Postgres at scale, swap in ``percentile_cont`` via a
        dialect-aware path.
        """
        with Session(self.engine) as s:
            stmt = (
                select(LLMCallRow.stage, LLMCallRow.latency_ms)
                .where(LLMCallRow.brand_slug == brand_slug)
                .where(LLMCallRow.called_at >= since)
                .where(LLMCallRow.success.is_(True))
            )
            if organization_id is not None:
                stmt = stmt.where(LLMCallRow.organization_id == organization_id)
            by_stage: dict[str, list[float]] = {}
            for stage, latency_ms in s.execute(stmt).all():
                by_stage.setdefault(stage, []).append(float(latency_ms))

        return {
            stage: _percentile_summary(values)
            for stage, values in by_stage.items()
        }

    def query_fallback_rate(
        self,
        brand_slug: str,
        since: datetime,
        organization_id: int | None = None,
    ) -> dict[str, dict[str, float]]:
        """Per-stage primary-vs-fallback breakdown for ``brand_slug`` since
        ``since``. Only successful calls are counted — a failed call means
        no model worked, not that the primary worked.

        Returns ``{stage: {"primary_count": int, "fallback_count": int,
        "primary_rate": float}}``. ``primary_rate`` is in ``[0.0, 1.0]``;
        a stage with zero successful calls is absent (avoids division by zero
        and dashboard NaN noise).
        """
        with Session(self.engine) as s:
            stmt = (
                select(
                    LLMCallRow.stage,
                    LLMCallRow.was_fallback,
                    func.count(LLMCallRow.id).label("n"),
                )
                .where(LLMCallRow.brand_slug == brand_slug)
                .where(LLMCallRow.called_at >= since)
                .where(LLMCallRow.success.is_(True))
                .group_by(LLMCallRow.stage, LLMCallRow.was_fallback)
            )
            if organization_id is not None:
                stmt = stmt.where(LLMCallRow.organization_id == organization_id)
            counts: dict[str, dict[bool, int]] = {}
            for stage, was_fallback, n in s.execute(stmt).all():
                counts.setdefault(stage, {})[bool(was_fallback)] = int(n)

        result: dict[str, dict[str, float]] = {}
        for stage, by_flag in counts.items():
            primary = by_flag.get(False, 0)
            fallback = by_flag.get(True, 0)
            total = primary + fallback
            if total == 0:
                continue
            result[stage] = {
                "primary_count": primary,
                "fallback_count": fallback,
                "primary_rate": primary / total,
            }
        return result
