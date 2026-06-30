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
