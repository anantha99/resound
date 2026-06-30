"""SQL-backed Memory. SQLite for dev, Postgres for prod — same code."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

from resound.config import env
from resound.core.memory import Memory
from resound.gateway import LLMGatewayError, LLMResponse
from resound.models import Classification, FeedbackEvent, RawSignal, Route


def _sha256(text: str) -> str:
    """SHA-256 hex digest of ``text`` (utf-8). Used for ``prompt_hash`` so
    operators can run "are we sending the same prompt twice" dedup analysis
    without storing prompt text (per design decision #30)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_slug: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
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

    def __init__(self, database_url: str | None = None):
        url = database_url or env("RESOUND_DATABASE_URL", "sqlite:///./data/resound.db")
        if url.startswith("sqlite:///"):
            from pathlib import Path
            db_path = Path(url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, echo=False, future=True)
        Base.metadata.create_all(self.engine)

    # ---- writes ----

    def has_seen(self, dedupe_key: str) -> bool:
        with Session(self.engine) as s:
            stmt = select(SignalRow.id).where(SignalRow.dedupe_key == dedupe_key)
            return s.execute(stmt).first() is not None

    def record_signal(self, brand_slug: str, raw: RawSignal) -> int:
        with Session(self.engine) as s:
            row = SignalRow(
                brand_slug=brand_slug,
                source=raw.source,
                external_id=raw.external_id,
                dedupe_key=raw.dedupe_key(),
                url=raw.url,
                author_handle=raw.author_handle,
                content=raw.content,
                posted_at=raw.posted_at,
                raw_metadata=raw.raw_metadata,
            )
            s.add(row)
            s.commit()
            return row.id

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
            s.add(row)
            s.commit()
            return row.id

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
            s.add(row)
            s.commit()
            return row.id

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
    ) -> int:
        """Record a failed LLM gateway call to the audit trail.

        Failure-path companion to :meth:`record_llm_call`. ``model`` /
        ``response_content`` / token / cost columns stay null because the
        call either never reached a model (config/auth errors) or never
        returned a parseable body. ``error.__class__.__name__`` is stored
        in ``error_class`` so dashboards can group failures by type without
        substring-matching the message.
        """
        with Session(self.engine) as s:
            row = LLMCallRow(
                brand_slug=brand_slug,
                signal_id=signal_id,
                stage=stage,
                model=None,
                prompt_hash=_sha256(prompt),
                response_content=None,
                tokens_in=None,
                tokens_out=None,
                cost_usd=None,
                latency_ms=latency_ms,
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
        self, brand_slug: str, since: datetime,
    ) -> list[dict[str, Any]]:
        """Aggregate LLM spend by ``(stage, model)`` for ``brand_slug`` since
        ``since``. Only successful calls are included — failure rows have
        no cost.

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
                .where(LLMCallRow.success.is_(True))
                .group_by(LLMCallRow.stage, LLMCallRow.model)
                .order_by(LLMCallRow.stage, LLMCallRow.model)
            )
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
        self, brand_slug: str, since: datetime,
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
            by_stage: dict[str, list[float]] = {}
            for stage, latency_ms in s.execute(stmt).all():
                by_stage.setdefault(stage, []).append(float(latency_ms))

        return {
            stage: _percentile_summary(values)
            for stage, values in by_stage.items()
        }

    def query_fallback_rate(
        self, brand_slug: str, since: datetime,
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
