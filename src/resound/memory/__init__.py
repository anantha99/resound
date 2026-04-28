"""SQL-backed Memory. SQLite for dev, Postgres for prod — same code."""

from __future__ import annotations

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
from resound.models import (
    ActionClass,
    Classification,
    FeedbackEvent,
    RawSignal,
    Route,
    Sentiment,
    Severity,
)


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

    classification: Mapped["ClassificationRow"] = relationship(back_populates="signal", uselist=False)
    route: Mapped["RouteRow"] = relationship(back_populates="signal", uselist=False)


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


class FeedbackRow(Base):
    __tablename__ = "feedback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[int] = mapped_column(ForeignKey("routes.id"), index=True)
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    actioned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SqlMemory(Memory):
    """SQL-backed Memory. Default URL: sqlite:///./data/resound.db."""

    def __init__(self, database_url: str | None = None):
        url = database_url or env("RESOUND_DATABASE_URL", "sqlite:///./data/resound.db")
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
                        "action_class": sig.classification.action_class if sig.classification else None,
                        "summary": sig.classification.summary if sig.classification else None,
                        "owner": sig.route.owner_id if sig.route else None,
                        "destination": sig.route.destination if sig.route else None,
                    }
                )
            return results
