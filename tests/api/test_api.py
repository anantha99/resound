from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resound.api import projections
from resound.api.app import app
from resound.api.openapi import client_openapi_schema
from resound.memory import SignalRow, SqlMemory
from resound.models import ActionClass, Classification, RawSignal, Route, Sentiment, Severity


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    return TestClient(app)


@pytest.fixture
def seeded_route(tmp_path, monkeypatch):
    db_path = tmp_path / "seeded.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    memory = SqlMemory()
    raw = RawSignal(
        source="reddit",
        external_id="abc123",
        url="https://reddit.com/r/liquiddeath/comments/abc123",
        author_handle="u/example",
        content="Shipping damage keeps happening.",
        posted_at=datetime.now(tz=UTC),
        raw_metadata={"subreddit": "liquiddeath", "score": 42, "num_comments": 7},
    )
    signal_id = memory.record_signal("liquiddeath", raw)
    classification_id = memory.record_classification(
        signal_id,
        Classification(
            is_about_brand=True,
            area="ops",
            subarea="shipping_damage",
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.HIGH,
            action_class=ActionClass.SPRINT,
            summary="Repeated shipping damage",
            root_cause_hypothesis="Packaging is under-spec for can compression.",
            confidence=0.84,
        ),
    )
    route_id = memory.record_route(
        signal_id,
        classification_id,
        Route(
            owner_id="@retail-ops",
            destination="@U01RETAIL",
            matched_rule="ops_retail_availability",
        ),
    )
    return {"route_id": route_id, "signal_id": signal_id}


def test_list_brands_includes_backend_and_demo_brands(client):
    response = client.get("/api/brands")

    assert response.status_code == 200
    slugs = {brand["slug"] for brand in response.json()}
    assert {"liquiddeath", "fulfil", "ridge", "oatly", "notion"}.issubset(slugs)
    liquid_death = next(brand for brand in response.json() if brand["slug"] == "liquiddeath")
    assert liquid_death["ownerOptions"]


def test_versioned_api_prefix_is_available(client):
    response = client.get("/api/v1/brands")

    assert response.status_code == 200
    assert any(brand["slug"] == "liquiddeath" for brand in response.json())


def test_list_signals_projects_memory_rows(client, seeded_route):
    response = client.get("/api/signals", params={"brandId": "liquiddeath", "period": "qtd"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    detail = body["signals"][0]
    assert detail["signal"]["id"] == seeded_route["signal_id"]
    assert detail["signal"]["source"] == "reddit"
    assert detail["classification"]["summary"] == "Repeated shipping damage"
    assert detail["route"]["owner"] == "@retail-ops"


def test_reroute_appends_handoff_and_projects_current_owner(client, seeded_route):
    response = client.patch(
        f"/api/routes/{seeded_route['route_id']}/reroute",
        json={"owner": "#triage", "note": "Needs central triage"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["owner"] == "#triage"
    assert body["reroutedFrom"] == "@retail-ops"

    audit = client.get("/api/routes", params={"brandId": "liquiddeath", "period": "qtd"}).json()
    assert audit[0]["owner"] == "#triage"
    assert audit[0]["reroutedFrom"] == "@retail-ops"


def test_reroute_rejects_owner_outside_brand_bundle(client, seeded_route):
    response = client.patch(
        f"/api/routes/{seeded_route['route_id']}/reroute",
        json={"owner": "@not-a-real-owner"},
    )

    assert response.status_code == 422


def test_feedback_records_latest_route_feedback(client, seeded_route):
    response = client.post(
        f"/api/routes/{seeded_route['route_id']}/feedback",
        json={"correct": False, "note": "Ops should not own this"},
    )

    assert response.status_code == 201
    assert response.json()["correct"] is False

    audit = client.get("/api/routes", params={"brandId": "liquiddeath", "period": "qtd"}).json()
    assert audit[0]["feedbackCorrect"] is False


@pytest.fixture
def stats_memory(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    return SqlMemory()


def _seed_signal(
    memory: SqlMemory,
    *,
    brand_slug: str = "liquiddeath",
    external_id: str,
    ingested_at: datetime,
    sentiment: Sentiment,
    severity: Severity,
    source: str = "reddit",
    area: str = "ops",
    subarea: str | None = "shipping_damage",
) -> int:
    raw = RawSignal(
        source=source,
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        author_handle="u/example",
        content="Test content",
        posted_at=datetime.now(tz=UTC),
        raw_metadata={"score": 10},
    )
    signal_id = memory.record_signal(brand_slug, raw)
    classification_id = memory.record_classification(
        signal_id,
        Classification(
            is_about_brand=True,
            area=area,
            subarea=subarea,
            sentiment=sentiment,
            severity=severity,
            action_class=ActionClass.SPRINT,
            summary="Summary",
            root_cause_hypothesis="Hypothesis",
            confidence=0.8,
        ),
    )
    memory.record_route(
        signal_id,
        classification_id,
        Route(owner_id="@retail-ops", destination="@U01", matched_rule="ops_retail_availability"),
    )
    # The window filters key off SignalRow.ingested_at (a DB default on insert), NOT
    # RawSignal.posted_at, so explicitly move the row into the desired window.
    with Session(memory.engine) as session:
        row = session.get(SignalRow, signal_id)
        row.ingested_at = ingested_at
        session.commit()
    return signal_id


def test_brand_stats_prior_empty_zeroes_all_deltas(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    # Only current-window signals; nothing in the prior 24h window.
    _seed_signal(
        stats_memory,
        external_id="cur-1",
        ingested_at=now - timedelta(hours=2),
        sentiment=Sentiment.NEGATIVE,
        severity=Severity.CRITICAL,
    )
    _seed_signal(
        stats_memory,
        external_id="cur-2",
        ingested_at=now - timedelta(hours=3),
        sentiment=Sentiment.POSITIVE,
        severity=Severity.HIGH,
    )

    stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)

    assert stats.net_sentiment_delta == 0
    assert stats.critical_delta == 0
    assert stats.volume_delta == 0.0
    assert stats.total_volume == 2


def test_brand_stats_negative_sentiment_not_clamped(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    for i in range(3):
        _seed_signal(
            stats_memory,
            external_id=f"neg-{i}",
            ingested_at=now - timedelta(hours=1),
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.MEDIUM,
        )
    _seed_signal(
        stats_memory,
        external_id="pos-1",
        ingested_at=now - timedelta(hours=1),
        sentiment=Sentiment.POSITIVE,
        severity=Severity.MEDIUM,
    )

    stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)

    assert stats.net_sentiment < 0


def test_brand_stats_sentiment_breakdown_sums_to_100(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    sentiments = [
        Sentiment.POSITIVE,
        Sentiment.POSITIVE,
        Sentiment.NEGATIVE,
        Sentiment.NEUTRAL,
        Sentiment.NEUTRAL,
        Sentiment.NEUTRAL,
        Sentiment.NEGATIVE,
    ]
    for i, sentiment in enumerate(sentiments):
        _seed_signal(
            stats_memory,
            external_id=f"sent-{i}",
            ingested_at=now - timedelta(hours=1),
            sentiment=sentiment,
            severity=Severity.LOW,
        )

    stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)
    breakdown = stats.sentiment_breakdown
    assert breakdown.positive + breakdown.neutral + breakdown.negative == 100


def test_brand_stats_source_mix_sums_to_100_and_alphabetical(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    sources = ["twitter", "reddit", "reddit", "g2", "twitter", "reddit", "g2"]
    for i, source in enumerate(sources):
        _seed_signal(
            stats_memory,
            external_id=f"src-{i}",
            ingested_at=now - timedelta(hours=1),
            sentiment=Sentiment.NEUTRAL,
            severity=Severity.LOW,
            source=source,
        )

    stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)
    mix = stats.source_mix
    assert sum(s.pct for s in mix) == 100
    assert [s.source for s in mix] == sorted(s.source for s in mix)


def test_brand_stats_emerging_is_period_scoped(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    # A signal older than 24h but within the quarter.
    _seed_signal(
        stats_memory,
        external_id="old-1",
        ingested_at=now - timedelta(days=10),
        sentiment=Sentiment.NEGATIVE,
        severity=Severity.HIGH,
        subarea="billing_dispute",
        area="billing",
    )

    qtd_stats = projections.brand_stats(stats_memory, "liquiddeath", "qtd", now=now)
    assert qtd_stats.top_emerging_issue.id != 0
    assert qtd_stats.top_emerging_issue.signal_count == 1

    day_stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)
    assert day_stats.top_emerging_issue.id == 0


def test_brand_stats_emerging_velocity_no_baseline(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    # Current 24h window has pattern signals; prior 24h window has none.
    for i in range(3):
        _seed_signal(
            stats_memory,
            external_id=f"nb-{i}",
            ingested_at=now - timedelta(hours=2),
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.HIGH,
        )

    stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)
    assert stats.top_emerging_issue.velocity_state == "no_baseline"


def test_brand_stats_emerging_velocity_accelerating(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    # Prior 24h window: 1 signal; current 24h window: 3 signals.
    _seed_signal(
        stats_memory,
        external_id="prev-1",
        ingested_at=now - timedelta(hours=30),
        sentiment=Sentiment.NEGATIVE,
        severity=Severity.HIGH,
    )
    for i in range(3):
        _seed_signal(
            stats_memory,
            external_id=f"acc-{i}",
            ingested_at=now - timedelta(hours=2),
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.HIGH,
        )

    stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)
    assert stats.top_emerging_issue.velocity_state == "accelerating"
    assert stats.top_emerging_issue.velocity_multiple > 1


def test_brand_stats_emerging_velocity_cooling(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    # Prior 24h window: 4 signals; current 24h window: 1 signal.
    for i in range(4):
        _seed_signal(
            stats_memory,
            external_id=f"prev-{i}",
            ingested_at=now - timedelta(hours=30),
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.HIGH,
        )
    _seed_signal(
        stats_memory,
        external_id="cool-1",
        ingested_at=now - timedelta(hours=2),
        sentiment=Sentiment.NEGATIVE,
        severity=Severity.HIGH,
    )

    stats = projections.brand_stats(stats_memory, "liquiddeath", "24h", now=now)
    assert stats.top_emerging_issue.velocity_state == "cooling"


@pytest.mark.parametrize(
    ("period", "expected_buckets"),
    [("24h", 12), ("7d", 7), ("30d", 10), ("qtd", 13)],
)
def test_brand_stats_trend_bucket_count_and_volume(stats_memory, period, expected_buckets):
    now = datetime(2026, 7, 17, 12, 0, 0)
    since = projections.period_since(period, now)
    span = now - since
    for i in range(5):
        # Spread signals across the elapsed window.
        offset = span * (i + 1) / 6
        _seed_signal(
            stats_memory,
            external_id=f"trend-{period}-{i}",
            ingested_at=since + offset,
            sentiment=Sentiment.NEUTRAL,
            severity=Severity.LOW,
        )

    stats = projections.brand_stats(stats_memory, "liquiddeath", period, now=now)
    assert len(stats.trend) == expected_buckets
    assert sum(p.volume for p in stats.trend) == stats.total_volume
    assert stats.total_volume == 5


def test_brand_stats_trend_all_empty_period(stats_memory):
    now = datetime(2026, 7, 17, 12, 0, 0)
    stats = projections.brand_stats(stats_memory, "liquiddeath", "7d", now=now)
    assert len(stats.trend) == 7
    assert all(
        p.volume == 0 and p.critical_count == 0 and p.net_sentiment == 0 for p in stats.trend
    )


def test_exported_openapi_schema_matches_react_client_base_path():
    schema = client_openapi_schema()

    assert schema["servers"] == [{"url": "/api", "description": "Base API path"}]
    assert "/brands" in schema["paths"]
    assert "/routes/{routeId}/reroute" in schema["paths"]
    assert "/api/brands" not in schema["paths"]
    assert "/api/v1/brands" not in schema["paths"]
