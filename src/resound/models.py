"""Shared Pydantic models. These are the contract between layers."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Sentiment(str, Enum):
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    MIXED = "mixed"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionClass(str, Enum):
    """How urgently does this signal need a human response."""

    IMMEDIATE = "immediate"
    SPRINT = "sprint"
    ROADMAP = "roadmap"
    FYI = "fyi"
    IGNORE = "ignore"


class RawSignal(BaseModel):
    """The output of a SourceAdapter. Layer-1 contract."""

    source: str  # e.g., "reddit", "g2", "twitter"
    external_id: str  # source-specific unique ID for dedup
    url: Optional[str] = None
    author_handle: Optional[str] = None
    content: str
    posted_at: datetime
    raw_metadata: dict[str, Any] = Field(default_factory=dict)

    def dedupe_key(self) -> str:
        return f"{self.source}::{self.external_id}"


class Classification(BaseModel):
    """The output of a Classifier. Layer-2 contract."""

    is_about_brand: bool
    area: str  # product, engineering, billing, cs, marketing, ops, other
    subarea: Optional[str] = None
    sentiment: Sentiment
    severity: Severity
    action_class: ActionClass
    summary: str
    root_cause_hypothesis: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: Optional[str] = None  # Claude's chain-of-thought, for audit


class Route(BaseModel):
    """The output of a Router. Layer-3 contract."""

    owner_id: str  # e.g., "@product-pm" or "#finance-urgent"
    destination: Optional[str] = None  # resolved via people.yaml
    matched_rule: Optional[str] = None  # which rule fired, for audit
    priority: str = "normal"  # normal | immediate
    notes: Optional[str] = None


class FeedbackEvent(BaseModel):
    """Layer-5 contract. Captured per route."""

    route_id: int
    correct: Optional[bool] = None  # right person?
    actioned: Optional[bool] = None  # did they actually do something?
    note: Optional[str] = None
    submitted_by: Optional[str] = None
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
