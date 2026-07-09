"""Public API schemas.

These DTOs are intentionally separate from SQLAlchemy rows and pipeline models.
They are the contract consumed by the React app and future mobile clients.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


Period = Literal["24h", "7d", "30d", "qtd"]


class Problem(ApiModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None


class HealthStatus(ApiModel):
    status: str
    version: str
    database: str
    brands_count: int


class ReadinessCheck(ApiModel):
    name: str
    status: Literal["ok", "warning", "error"]
    detail: str | None = None


class ReadinessStatus(ApiModel):
    status: Literal["ok", "degraded"]
    checks: list[ReadinessCheck]


class OwnerOption(ApiModel):
    owner: str
    label: str
    hint: str


class Brand(ApiModel):
    id: int
    name: str
    slug: str
    description: str
    primary_contact: str
    sources_active: list[str]
    last_ingested: str | None
    tagline: str
    owner_options: list[OwnerOption] = Field(default_factory=list)


class SourceStat(ApiModel):
    source: str
    count: int
    pct: float


class SentimentBreakdown(ApiModel):
    positive: float
    neutral: float
    negative: float


class PatternSummary(ApiModel):
    id: int
    name: str
    area: str
    signal_count: int
    weekly_velocity: int
    velocity_multiple: float


class BrandStats(ApiModel):
    brand_id: str
    period: str
    net_sentiment: int
    net_sentiment_delta: int
    critical_count: int
    critical_delta: int
    total_volume: int
    volume_delta: float
    source_mix: list[SourceStat]
    sentiment_breakdown: SentimentBreakdown
    top_emerging_issue: PatternSummary
    last_ingested: str | None = None


class Signal(ApiModel):
    id: int
    brand_id: str
    source: str
    external_id: str
    url: str
    author_handle: str
    author_meta: str | None = None
    reach: int | None = None
    content: str
    posted_at: str
    created_at: str


class Classification(ApiModel):
    id: int
    signal_id: int
    is_about_brand: bool
    area: str
    subarea: str | None = None
    sentiment: Literal["negative", "neutral", "positive", "mixed"]
    severity: Literal["low", "medium", "high", "critical"]
    action_class: Literal["immediate", "sprint", "roadmap", "fyi", "ignore"]
    root_cause_hypothesis: str
    summary: str
    confidence: float


class Route(ApiModel):
    id: int
    signal_id: int
    classification_id: int
    owner: str
    rule_matched: str | None
    confidence: float
    rerouted_from: str | None = None
    created_at: str


class SignalDetail(ApiModel):
    signal: Signal
    classification: Classification
    route: Route
    pattern_id: int | None = None
    pattern_name: str | None = None


class SignalList(ApiModel):
    signals: list[SignalDetail]
    total: int


class RouteAudit(ApiModel):
    id: int
    signal_id: int
    owner: str
    area: str
    severity: str
    sentiment: str
    source: str
    content: str
    summary: str
    confidence: float
    rule_matched: str | None
    rerouted_from: str | None = None
    created_at: str
    feedback_correct: bool | None


class RerouteInput(ApiModel):
    owner: str
    note: str | None = None
    submitted_by: str | None = None


class FeedbackInput(ApiModel):
    correct: bool
    note: str | None = None
    actioned: bool | None = None
    submitted_by: str | None = None


class FeedbackEvent(ApiModel):
    id: int
    route_id: int
    correct: bool
    note: str | None = None
    created_at: str


class Pattern(ApiModel):
    id: int
    brand_id: str
    name: str
    area: str
    blurb: str
    signal_count: int
    weekly_velocity: int
    velocity_multiple: float
    started_at: str


class PatternDetail(ApiModel):
    pattern: Pattern
    signals: list[SignalDetail]


class SourceSyncInput(ApiModel):
    brand_id: str


class ReportRunCreateInput(ApiModel):
    brand_id: str
    role: str
    timeframe: str = "7d"
    report_config_id: int | None = None


class WorkflowJob(ApiModel):
    id: int
    workflow_id: str
    run_id: str | None = None
    workflow_type: str
    status: str
    task_queue: str | None = None
    created_at: str


class ListeningProfileSetupInput(ApiModel):
    brand_id: str
    brand_names: list[str]
    product_names: list[str] = Field(default_factory=list)
    competitor_names: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    locale: str | None = None
    language: str = "en"
    setup_notes: str | None = None


class ListeningProfileSuggestionDecision(ApiModel):
    decision: Literal["accept", "edit", "reject"]
    edited_value: str | None = None


class ListeningProfileSuggestion(ApiModel):
    id: int
    profile_id: int
    suggestion_type: str
    value: str
    reason: str | None = None
    status: str
    created_at: str
    resolved_at: str | None = None


class ReportTemplate(ApiModel):
    role: str
    display_name: str
    sections: list[str]


class ReportRun(ApiModel):
    id: int
    report_config_id: int | None
    role: str
    timeframe: str
    status: str
    markdown: str
    generated_at: str


class AgentSession(ApiModel):
    id: int
    agent_type: str
    user_goal: str
    status: str
    created_at: str


class PublicFeedItem(ApiModel):
    id: int
    brand_id: str
    source: str
    content: str
    posted_at: str
    source_url: str | None = None


class PublicFeed(ApiModel):
    items: list[PublicFeedItem]
    capped: bool = True
    export_available: bool = False


class PublicFeedModerationInput(ApiModel):
    action: Literal["show", "hide", "takedown", "no_export"]
    reason: str | None = None
    actor: str | None = None


class PublicFeedModerationEvent(ApiModel):
    id: int
    signal_id: int
    action: str
    reason: str | None = None
    actor: str | None = None
    created_at: str


class SourceHealth(ApiModel):
    source_type: str
    provider: str
    status: str
    last_success_at: str | None = None
    last_failure_at: str | None = None
    last_run_id: str | None = None
    item_count: int
    error_message: str | None = None


class LLMTelemetry(ApiModel):
    brand_id: str
    period: Period
    costs: list[dict]
    latency: dict[str, dict[str, float]]
    fallback_rate: dict[str, dict[str, float]]


class EvaluationSummary(ApiModel):
    brand_id: str
    report_runs_by_status: dict[str, int]
    source_failure_count: int
    total_llm_cost_usd: float
