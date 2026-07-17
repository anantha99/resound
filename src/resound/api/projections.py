"""Read models and command helpers for the Resound API."""

from __future__ import annotations

import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from resound.api import schemas
from resound.config import BrandConfig, load_brand_config
from resound.memory import (
    BrandRow,
    ClassificationRow,
    FeedbackRow,
    RouteHandoffRow,
    RouteRow,
    SignalRow,
    SqlMemory,
)
from resound.models import FeedbackEvent as DomainFeedbackEvent
from resound.tenancy import TenantContext

BRANDS_DIR = Path("brands")


@dataclass(frozen=True)
class SignalJoinedRow:
    signal: SignalRow
    classification: ClassificationRow
    route: RouteRow


def period_since(period: schemas.Period, now: datetime | None = None) -> datetime:
    now = now if now is not None else datetime.utcnow()
    if period == "24h":
        return now - timedelta(days=1)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)

    start_month = ((now.month - 1) // 3) * 3 + 1
    return datetime(now.year, start_month, 1)


def list_brand_slugs(brands_dir: Path = BRANDS_DIR) -> list[str]:
    if not brands_dir.is_dir():
        return []
    return sorted(
        path.name for path in brands_dir.iterdir()
        if path.is_dir() and (path / "brand.yaml").exists()
    )


def list_brands(memory: SqlMemory, tenant: TenantContext | None = None) -> list[schemas.Brand]:
    if tenant is not None:
        tenant_brands = memory.list_brands_for_tenant(tenant)
        return [_tenant_brand_to_schema(row, memory) for row in tenant_brands]

    brands = [
        brand_to_schema(idx, load_brand_config(slug), memory)
        for idx, slug in enumerate(list_brand_slugs(), start=1)
    ]
    return sorted(brands, key=lambda brand: (brand.last_ingested is None, brand.name.lower()))


def get_brand(
    slug: str,
    memory: SqlMemory,
    tenant: TenantContext | None = None,
) -> schemas.Brand | None:
    if tenant is not None:
        for brand in memory.list_brands_for_tenant(tenant):
            if brand.slug == slug:
                return _tenant_brand_to_schema(brand, memory)
        return None

    slugs = list_brand_slugs()
    if slug not in slugs:
        return None
    return brand_to_schema(slugs.index(slug) + 1, load_brand_config(slug), memory)


def brand_to_schema(index: int, brand: BrandConfig, memory: SqlMemory) -> schemas.Brand:
    primary_contact = _primary_contact(brand)
    active_sources = [
        source for source, config in brand.sources.items()
        if isinstance(config, dict) and config.get("enabled")
    ]

    return schemas.Brand(
        id=index,
        name=brand.name,
        slug=brand.slug,
        description=brand.description,
        primary_contact=primary_contact,
        sources_active=active_sources,
        last_ingested=_last_ingested(memory, brand.slug),
        tagline=brand.description,
        owner_options=owner_options_for_brand(brand),
    )


def _tenant_brand_to_schema(row: BrandRow, memory: SqlMemory) -> schemas.Brand:
    source_config = row.source_config or {}
    active_sources = [
        source for source, config in source_config.items()
        if not isinstance(config, dict) or config.get("enabled", True)
    ]
    return schemas.Brand(
        id=row.id,
        name=row.display_name,
        slug=row.slug,
        description=row.description,
        primary_contact="operator",
        sources_active=active_sources,
        last_ingested=_last_ingested(memory, row.slug, organization_id=row.organization_id),
        tagline=row.description,
        owner_options=[],
    )


def owner_options_for_brand(brand: BrandConfig) -> list[schemas.OwnerOption]:
    options: list[schemas.OwnerOption] = []
    for owner, info in sorted(brand.people.get("people", {}).items()):
        label = info.get("name") or owner
        options.append(schemas.OwnerOption(owner=owner, label=label, hint="Person"))
    for owner, info in sorted(brand.people.get("channels", {}).items()):
        label = info.get("description") or info.get("slack_channel") or owner
        options.append(schemas.OwnerOption(owner=owner, label=label, hint="Channel"))
    return options


def valid_owner_ids(brand: BrandConfig) -> set[str]:
    return {
        *brand.people.get("people", {}).keys(),
        *brand.people.get("channels", {}).keys(),
    }


def brand_stats(
    memory: SqlMemory,
    brand_slug: str,
    period: schemas.Period,
    tenant: TenantContext | None = None,
    now: datetime | None = None,
) -> schemas.BrandStats:
    now = now if now is not None else datetime.utcnow()
    since = period_since(period, now)
    previous_since = since - (now - since)
    current = _joined_rows(memory, brand_slug, tenant=tenant, since=since, limit=None, offset=0)
    previous = _joined_rows(
        memory,
        brand_slug,
        tenant=tenant,
        since=previous_since,
        before=since,
        limit=None,
        offset=0,
    )
    previous_empty = len(previous) == 0
    current_classes = [row.classification for row in current]
    previous_classes = [row.classification for row in previous]

    current_sentiment = _sentiment_stats(current_classes)
    previous_sentiment = _sentiment_stats(previous_classes)
    current_critical = _critical_count(current_classes)
    previous_critical = _critical_count(previous_classes)
    source_mix = _source_mix(row.signal.source for row in current)
    patterns = list_patterns(memory, brand_slug, area=None, since=since, tenant=tenant)
    top_pattern = (
        _emerging_summary(patterns[0], current, previous)
        if patterns
        else _empty_pattern_summary()
    )

    net_sentiment_delta = (
        0 if previous_empty else current_sentiment["score"] - previous_sentiment["score"]
    )
    critical_delta = 0 if previous_empty else current_critical - previous_critical

    return schemas.BrandStats(
        brand_id=brand_slug,
        period=period,
        net_sentiment=current_sentiment["score"],
        net_sentiment_delta=net_sentiment_delta,
        critical_count=current_critical,
        critical_delta=critical_delta,
        total_volume=len(current),
        volume_delta=_volume_delta(len(current), len(previous)),
        source_mix=source_mix,
        sentiment_breakdown=schemas.SentimentBreakdown(
            positive=current_sentiment["positive"],
            neutral=current_sentiment["neutral"],
            negative=current_sentiment["negative"],
        ),
        top_emerging_issue=top_pattern,
        trend=_trend_series(current, period, since, now),
        last_ingested=_last_ingested(memory, brand_slug),
    )


def list_signals(
    memory: SqlMemory,
    *,
    tenant: TenantContext | None = None,
    brand_slug: str | None,
    source: str | None,
    area: str | None,
    severity: str | None,
    sentiment: str | None,
    period: schemas.Period,
    limit: int,
    offset: int,
) -> schemas.SignalList:
    rows = _joined_rows(
        memory,
        brand_slug,
        tenant=tenant,
        since=period_since(period),
        source=_normalize_source(source),
        area=area,
        severity=severity,
        sentiment=sentiment,
        limit=limit,
        offset=offset,
    )
    total = _joined_count(
        memory,
        brand_slug,
        tenant=tenant,
        since=period_since(period),
        source=_normalize_source(source),
        area=area,
        severity=severity,
        sentiment=sentiment,
    )
    route_ids = [row.route.id for row in rows]
    latest_handoffs = _latest_handoffs(memory, route_ids)
    return schemas.SignalList(
        signals=[signal_detail(row, latest_handoffs.get(row.route.id)) for row in rows],
        total=total,
    )


def get_signal(
    memory: SqlMemory,
    signal_id: int,
    tenant: TenantContext | None = None,
) -> schemas.SignalDetail | None:
    rows = _joined_rows(memory, None, tenant=tenant, signal_id=signal_id, limit=1, offset=0)
    if not rows:
        return None
    handoff = _latest_handoffs(memory, [rows[0].route.id]).get(rows[0].route.id)
    return signal_detail(rows[0], handoff)


def critical_signals(
    memory: SqlMemory,
    brand_slug: str | None,
    period: schemas.Period,
    tenant: TenantContext | None = None,
) -> list[schemas.SignalDetail]:
    rows = _joined_rows(
        memory,
        brand_slug,
        tenant=tenant,
        since=period_since(period),
        severities=["critical", "high"],
        limit=100,
        offset=0,
    )
    latest_handoffs = _latest_handoffs(memory, [row.route.id for row in rows])
    return [signal_detail(row, latest_handoffs.get(row.route.id)) for row in rows]


def list_routes(
    memory: SqlMemory,
    *,
    tenant: TenantContext | None = None,
    brand_slug: str | None,
    period: schemas.Period,
    limit: int,
) -> list[schemas.RouteAudit]:
    rows = _joined_rows(
        memory,
        brand_slug,
        tenant=tenant,
        since=period_since(period),
        limit=limit,
        offset=0,
    )
    route_ids = [row.route.id for row in rows]
    latest_handoffs = _latest_handoffs(memory, route_ids)
    latest_feedback = _latest_feedback(memory, route_ids)
    return [
        route_audit(row, latest_handoffs.get(row.route.id), latest_feedback.get(row.route.id))
        for row in rows
    ]


def reroute(
    memory: SqlMemory,
    *,
    tenant: TenantContext | None = None,
    route_id: int,
    owner: str,
    note: str | None,
    submitted_by: str | None,
    idempotency_key: str | None,
) -> schemas.RouteAudit | None:
    row = _joined_row_for_route(memory, route_id, tenant=tenant)
    if row is None:
        return None

    current_handoff = _latest_handoffs(memory, [route_id]).get(route_id)
    current_owner = current_handoff.to_owner if current_handoff else row.route.owner_id
    memory.record_route_handoff(
        route_id=route_id,
        from_owner=current_owner,
        to_owner=owner,
        note=note,
        submitted_by=submitted_by,
        idempotency_key=idempotency_key,
    )
    handoff = _latest_handoffs(memory, [route_id]).get(route_id)
    feedback = _latest_feedback(memory, [route_id]).get(route_id)
    return route_audit(row, handoff, feedback)


def submit_feedback(
    memory: SqlMemory,
    *,
    tenant: TenantContext | None = None,
    route_id: int,
    correct: bool,
    note: str | None,
    actioned: bool | None,
    submitted_by: str | None,
) -> schemas.FeedbackEvent | None:
    row = _joined_row_for_route(memory, route_id, tenant=tenant)
    if row is None:
        return None

    feedback_id = memory.record_feedback(
        DomainFeedbackEvent(
            route_id=route_id,
            correct=correct,
            actioned=actioned,
            note=note,
            submitted_by=submitted_by,
        )
    )
    latest = _latest_feedback(memory, [route_id]).get(route_id)
    if latest is None or latest.id != feedback_id:
        latest = _feedback_by_id(memory, feedback_id)
    if latest is None:
        return None
    return schemas.FeedbackEvent(
        id=latest.id,
        route_id=latest.route_id,
        correct=bool(latest.correct),
        note=latest.note,
        created_at=_iso(latest.submitted_at),
    )


def list_patterns(
    memory: SqlMemory,
    brand_slug: str | None,
    area: str | None,
    tenant: TenantContext | None = None,
    since: datetime | None = None,
) -> list[schemas.Pattern]:
    rows = _joined_rows(memory, brand_slug, tenant=tenant, since=since, limit=None, offset=0)
    if area:
        rows = [row for row in rows if row.classification.area == area]
    groups = _group_by_pattern(rows)

    patterns = [_pattern_from_group(key, grouped) for key, grouped in groups.items()]
    return sorted(patterns, key=lambda p: (p.velocity_multiple, p.signal_count), reverse=True)


def get_pattern(
    memory: SqlMemory,
    pattern_id: int,
    tenant: TenantContext | None = None,
) -> schemas.PatternDetail | None:
    for pattern in list_patterns(memory, None, None, tenant=tenant):
        if pattern.id != pattern_id:
            continue
        brand_slug = pattern.brand_id
        key = _pattern_key_from_name(pattern.name)
        rows = [
            row for row in _joined_rows(memory, brand_slug, tenant=tenant, limit=None, offset=0)
            if (row.classification.subarea or row.classification.area) == key
        ]
        latest_handoffs = _latest_handoffs(memory, [row.route.id for row in rows])
        return schemas.PatternDetail(
            pattern=pattern,
            signals=[signal_detail(row, latest_handoffs.get(row.route.id)) for row in rows[:50]],
        )
    return None


def signal_detail(
    row: SignalJoinedRow, handoff: RouteHandoffRow | None = None,
) -> schemas.SignalDetail:
    key = row.classification.subarea or row.classification.area
    return schemas.SignalDetail(
        signal=signal_schema(row.signal),
        classification=classification_schema(row.classification),
        route=route_schema(row.route, row.classification, handoff),
        pattern_id=_pattern_id(row.signal.brand_slug, key),
        pattern_name=_pattern_name(key),
    )


def signal_schema(row: SignalRow) -> schemas.Signal:
    return schemas.Signal(
        id=row.id,
        brand_id=row.brand_slug,
        source=row.source,
        external_id=row.external_id,
        url=row.url or "",
        author_handle=row.author_handle or "unknown",
        author_meta=_author_meta(row),
        reach=_reach(row),
        content=row.content,
        posted_at=_iso(row.posted_at),
        created_at=_iso(row.ingested_at),
    )


def classification_schema(row: ClassificationRow) -> schemas.Classification:
    return schemas.Classification(
        id=row.id,
        signal_id=row.signal_id,
        is_about_brand=row.is_about_brand,
        area=row.area,
        subarea=row.subarea,
        sentiment=row.sentiment,
        severity=row.severity,
        action_class=row.action_class,
        root_cause_hypothesis=row.root_cause_hypothesis or "",
        summary=row.summary,
        confidence=row.confidence,
    )


def route_schema(
    row: RouteRow, classification: ClassificationRow, handoff: RouteHandoffRow | None,
) -> schemas.Route:
    return schemas.Route(
        id=row.id,
        signal_id=row.signal_id,
        classification_id=row.classification_id,
        owner=handoff.to_owner if handoff else row.owner_id,
        rule_matched=row.matched_rule,
        confidence=classification.confidence,
        rerouted_from=handoff.from_owner if handoff else None,
        created_at=_iso(handoff.created_at if handoff else row.routed_at),
    )


def route_audit(
    row: SignalJoinedRow,
    handoff: RouteHandoffRow | None,
    feedback: FeedbackRow | None,
) -> schemas.RouteAudit:
    route = route_schema(row.route, row.classification, handoff)
    return schemas.RouteAudit(
        id=row.route.id,
        signal_id=row.signal.id,
        owner=route.owner,
        area=row.classification.area,
        severity=row.classification.severity,
        sentiment=row.classification.sentiment,
        source=row.signal.source,
        content=row.signal.content,
        summary=row.classification.summary,
        confidence=row.classification.confidence,
        rule_matched=row.route.matched_rule,
        rerouted_from=route.rerouted_from,
        created_at=route.created_at,
        feedback_correct=feedback.correct if feedback else None,
    )


def _joined_rows(
    memory: SqlMemory,
    brand_slug: str | None,
    *,
    tenant: TenantContext | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    source: str | None = None,
    area: str | None = None,
    severity: str | None = None,
    sentiment: str | None = None,
    severities: list[str] | None = None,
    signal_id: int | None = None,
    limit: int | None,
    offset: int,
) -> list[SignalJoinedRow]:
    with Session(memory.engine) as session:
        stmt = (
            select(SignalRow, ClassificationRow, RouteRow)
            .join(ClassificationRow, ClassificationRow.signal_id == SignalRow.id)
            .join(RouteRow, RouteRow.signal_id == SignalRow.id)
            .order_by(SignalRow.ingested_at.desc(), SignalRow.id.desc())
        )
        stmt = _apply_join_filters(
            stmt,
            brand_slug=brand_slug,
            tenant=tenant,
            since=since,
            before=before,
            source=source,
            area=area,
            severity=severity,
            sentiment=sentiment,
            severities=severities,
            signal_id=signal_id,
        )
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(max(1, min(limit, 200)))
        return [SignalJoinedRow(sig, cls, route) for sig, cls, route in session.execute(stmt).all()]


def _joined_count(
    memory: SqlMemory,
    brand_slug: str | None,
    *,
    tenant: TenantContext | None = None,
    since: datetime | None,
    source: str | None,
    area: str | None,
    severity: str | None,
    sentiment: str | None,
) -> int:
    with Session(memory.engine) as session:
        stmt = (
            select(func.count(SignalRow.id))
            .join(ClassificationRow, ClassificationRow.signal_id == SignalRow.id)
            .join(RouteRow, RouteRow.signal_id == SignalRow.id)
        )
        stmt = _apply_join_filters(
            stmt,
            brand_slug=brand_slug,
            tenant=tenant,
            since=since,
            before=None,
            source=source,
            area=area,
            severity=severity,
            sentiment=sentiment,
            severities=None,
            signal_id=None,
        )
        return int(session.execute(stmt).scalar_one())


def _apply_join_filters(stmt, **filters):
    if filters["tenant"] is not None:
        stmt = stmt.where(SignalRow.organization_id == filters["tenant"].organization_id)
    if filters["brand_slug"]:
        stmt = stmt.where(SignalRow.brand_slug == filters["brand_slug"])
    if filters["since"]:
        stmt = stmt.where(SignalRow.ingested_at >= filters["since"])
    if filters["before"]:
        stmt = stmt.where(SignalRow.ingested_at < filters["before"])
    if filters["source"]:
        stmt = stmt.where(SignalRow.source == filters["source"])
    if filters["area"]:
        stmt = stmt.where(ClassificationRow.area == filters["area"])
    if filters["severity"]:
        stmt = stmt.where(ClassificationRow.severity == filters["severity"])
    if filters["sentiment"]:
        stmt = stmt.where(ClassificationRow.sentiment == filters["sentiment"])
    if filters["severities"]:
        stmt = stmt.where(ClassificationRow.severity.in_(filters["severities"]))
    if filters["signal_id"]:
        stmt = stmt.where(SignalRow.id == filters["signal_id"])
    return stmt


def _joined_row_for_route(
    memory: SqlMemory,
    route_id: int,
    tenant: TenantContext | None = None,
) -> SignalJoinedRow | None:
    with Session(memory.engine) as session:
        stmt = (
            select(SignalRow, ClassificationRow, RouteRow)
            .join(ClassificationRow, ClassificationRow.signal_id == SignalRow.id)
            .join(RouteRow, RouteRow.signal_id == SignalRow.id)
            .where(RouteRow.id == route_id)
        )
        if tenant is not None:
            stmt = stmt.where(SignalRow.organization_id == tenant.organization_id)
        row = session.execute(stmt).first()
        if row is None:
            return None
        sig, cls, route = row
        return SignalJoinedRow(sig, cls, route)


def _latest_handoffs(memory: SqlMemory, route_ids: list[int]) -> dict[int, RouteHandoffRow]:
    if not route_ids:
        return {}
    with Session(memory.engine) as session:
        stmt = (
            select(RouteHandoffRow)
            .where(RouteHandoffRow.route_id.in_(route_ids))
            .order_by(RouteHandoffRow.route_id, RouteHandoffRow.created_at, RouteHandoffRow.id)
        )
        latest: dict[int, RouteHandoffRow] = {}
        for row in session.execute(stmt).scalars():
            latest[row.route_id] = row
        return latest


def _latest_feedback(memory: SqlMemory, route_ids: list[int]) -> dict[int, FeedbackRow]:
    if not route_ids:
        return {}
    with Session(memory.engine) as session:
        stmt = (
            select(FeedbackRow)
            .where(FeedbackRow.route_id.in_(route_ids))
            .order_by(FeedbackRow.route_id, FeedbackRow.submitted_at, FeedbackRow.id)
        )
        latest: dict[int, FeedbackRow] = {}
        for row in session.execute(stmt).scalars():
            latest[row.route_id] = row
        return latest


def _feedback_by_id(memory: SqlMemory, feedback_id: int) -> FeedbackRow | None:
    with Session(memory.engine) as session:
        return session.execute(
            select(FeedbackRow).where(FeedbackRow.id == feedback_id),
        ).scalar_one_or_none()


def _sentiment_stats(rows: list[ClassificationRow]) -> dict[str, int]:
    total = len(rows)
    if total == 0:
        return {"score": 0, "positive": 0, "neutral": 0, "negative": 0}
    positive = len([row for row in rows if row.sentiment == "positive"])
    negative = len([row for row in rows if row.sentiment == "negative"])
    neutral = total - positive - negative
    pos_pct, neu_pct, neg_pct = _largest_remainder(
        {"positive": positive, "neutral": neutral, "negative": negative},
        total,
    )
    return {
        "score": round(((positive - negative) / total) * 100),
        "positive": pos_pct,
        "neutral": neu_pct,
        "negative": neg_pct,
    }


def _largest_remainder(counts: dict[str, int], total: int) -> list[int]:
    """Allocate integer percentages summing to exactly 100 (largest remainder)."""
    if total == 0:
        return [0 for _ in counts]
    exact = {key: (count / total) * 100 for key, count in counts.items()}
    floors = {key: int(value) for key, value in exact.items()}
    remainder = 100 - sum(floors.values())
    order = sorted(
        counts.keys(),
        key=lambda key: (exact[key] - floors[key], counts[key]),
        reverse=True,
    )
    for key in order[:remainder]:
        floors[key] += 1
    return [floors[key] for key in counts]


def _critical_count(rows: list[ClassificationRow]) -> int:
    return len([row for row in rows if row.severity in {"critical", "high"}])


def _trend_buckets(period: schemas.Period) -> int:
    return {"24h": 12, "7d": 7, "30d": 10, "qtd": 13}.get(period, 12)


def _trend_series(
    rows: list[SignalJoinedRow],
    period: schemas.Period,
    since: datetime,
    now: datetime,
) -> list[schemas.TrendPoint]:
    """Divide the elapsed window (since -> now) into N equal buckets and summarize each."""
    count = _trend_buckets(period)
    span = now - since
    if count <= 0 or span <= timedelta(0):
        return []
    width = span / count
    buckets: list[list[SignalJoinedRow]] = [[] for _ in range(count)]
    for row in rows:
        ingested = row.signal.ingested_at
        if ingested < since or ingested >= now:
            continue
        index = int((ingested - since) / width)
        index = min(max(index, 0), count - 1)
        buckets[index].append(row)

    points: list[schemas.TrendPoint] = []
    for index, bucket in enumerate(buckets):
        bucket_classes = [row.classification for row in bucket]
        points.append(
            schemas.TrendPoint(
                label=str(index),
                net_sentiment=_sentiment_stats(bucket_classes)["score"],
                critical_count=_critical_count(bucket_classes),
                volume=len(bucket),
            )
        )
    return points


def _source_mix(sources: Iterable[str]) -> list[schemas.SourceStat]:
    counts: dict[str, int] = {}
    for source in sources:
        counts[source] = counts.get(source, 0) + 1
    total = sum(counts.values())
    if total == 0:
        return []
    ordered = sorted(counts.items())
    pcts = _largest_remainder({source: count for source, count in ordered}, total)
    return [
        schemas.SourceStat(source=source, count=count, pct=pct)
        for (source, count), pct in zip(ordered, pcts, strict=True)
    ]


def _volume_delta(current: int, previous: int) -> float:
    if previous == 0:
        return 0.0
    return round(((current - previous) / previous) * 100, 1)


def _primary_contact(brand: BrandConfig) -> str:
    contacts = brand.brand.get("primary_contacts") or []
    if not contacts:
        return "operator"
    first = contacts[0]
    return first.get("email") or first.get("name") or "operator"


def _last_ingested(
    memory: SqlMemory,
    brand_slug: str,
    *,
    organization_id: int | None = None,
) -> str | None:
    with Session(memory.engine) as session:
        stmt = select(func.max(SignalRow.ingested_at)).where(SignalRow.brand_slug == brand_slug)
        if organization_id is not None:
            stmt = stmt.where(SignalRow.organization_id == organization_id)
        value = session.execute(stmt).scalar_one_or_none()
        return _iso(value) if value else None


def _normalize_source(source: str | None) -> str | None:
    if not source:
        return None
    return source.strip().lower()


def _author_meta(row: SignalRow) -> str | None:
    meta = row.raw_metadata or {}
    if row.source == "reddit":
        subreddit = meta.get("subreddit") or meta.get("channel")
        comments = meta.get("num_comments")
        if subreddit and comments is not None:
            return f"r/{subreddit} · {comments} comments"
        if subreddit:
            return f"r/{subreddit}"
    if row.source == "g2":
        rating = meta.get("rating")
        if rating is not None:
            return f"G2 · {rating} stars"
    if row.source == "twitter":
        reach = meta.get("reach")
        if reach is not None:
            return f"X/Twitter · {reach} engagements"
    return None


def _reach(row: SignalRow) -> int | None:
    meta = row.raw_metadata or {}
    if row.source == "reddit":
        return _int_or_none(meta.get("score"))
    if row.source == "twitter":
        return _int_or_none(meta.get("reach"))
    rating = meta.get("rating")
    return int(float(rating) * 20) if rating is not None else None


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pattern_from_group(key: str, rows: list[SignalJoinedRow]) -> schemas.Pattern:
    first = min(rows, key=lambda row: row.signal.ingested_at)
    last_week = datetime.utcnow() - timedelta(days=7)
    weekly = len([row for row in rows if row.signal.ingested_at >= last_week])
    previous_avg = max((len(rows) - weekly) / 4, 1)
    return schemas.Pattern(
        id=_pattern_id(first.signal.brand_slug, key),
        brand_id=first.signal.brand_slug,
        name=_pattern_name(key),
        area=first.classification.area,
        blurb=(
            f"Signals grouped around {key.replace('_', ' ')}. "
            "This is derived from the memory layer and can be replaced by a "
            "dedicated clustering job later without changing the client contract."
        ),
        signal_count=len(rows),
        weekly_velocity=weekly,
        velocity_multiple=round(weekly / previous_avg, 1),
        started_at=_month_label(first.signal.ingested_at),
    )


def _pattern_summary(pattern: schemas.Pattern) -> schemas.PatternSummary:
    return schemas.PatternSummary(
        id=pattern.id,
        name=pattern.name,
        area=pattern.area,
        signal_count=pattern.signal_count,
        weekly_velocity=pattern.weekly_velocity,
        velocity_multiple=pattern.velocity_multiple,
        velocity_state="no_baseline",
    )


def _empty_pattern_summary() -> schemas.PatternSummary:
    return schemas.PatternSummary(
        id=0,
        name="No emerging patterns yet",
        area="other",
        signal_count=0,
        weekly_velocity=0,
        velocity_multiple=1.0,
        velocity_state="no_baseline",
    )


def _pattern_group_key(row: SignalJoinedRow) -> str:
    return row.classification.subarea or row.classification.area


def _group_by_pattern(rows: list[SignalJoinedRow]) -> dict[str, list[SignalJoinedRow]]:
    groups: dict[str, list[SignalJoinedRow]] = {}
    for row in rows:
        groups.setdefault(_pattern_group_key(row), []).append(row)
    return groups


def _emerging_summary(
    top_pattern: schemas.Pattern,
    current: list[SignalJoinedRow],
    previous: list[SignalJoinedRow],
) -> schemas.PatternSummary:
    """Build the emerging-issue summary with honest velocity vs a comparable prior window.

    ``top_pattern`` supplies name/area/signal_count/id (period-scoped via ``list_patterns``);
    velocity_multiple and velocity_state are overridden using the current vs previous window
    counts for the top current pattern key.
    """
    summary = _pattern_summary(top_pattern)
    top_key = _pattern_key_from_name(top_pattern.name)
    current_count = len(_group_by_pattern(current).get(top_key, []))
    previous_count = len(_group_by_pattern(previous).get(top_key, []))

    if previous_count == 0:
        # _pattern_summary already defaults velocity_state to "no_baseline".
        return summary

    ratio = round(current_count / previous_count, 1)
    if ratio > 1.05:
        state = "accelerating"
    elif ratio < 0.95:
        state = "cooling"
    else:
        state = "steady"
    return summary.model_copy(update={"velocity_multiple": ratio, "velocity_state": state})


def _pattern_id(brand_slug: str, key: str) -> int:
    return zlib.crc32(f"{brand_slug}:{key}".encode()) & 0x7FFFFFFF


def _pattern_name(key: str) -> str:
    return key.replace("_", " ").title()


def _pattern_key_from_name(name: str) -> str:
    return name.lower().replace(" ", "_")


def _month_label(value: datetime) -> str:
    return value.strftime("%b %Y")


def _iso(value: datetime) -> str:
    return value.isoformat()
