from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from resound.api.app import app
from resound.api.openapi import client_openapi_schema
from resound.memory import SignalRow, SqlMemory
from resound.models import ActionClass, Classification, RawSignal, Route, Sentiment, Severity


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RESOUND_REQUIRE_TENANT_HEADER", "false")
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
    assert detail["signal"]["canonicalPlatform"] == "reddit"
    assert detail["signal"]["contentKind"] == "post"
    assert detail["signal"]["metrics"]["upvotes"] == 42
    assert detail["signal"]["metrics"]["comments"] == 7
    assert detail["signal"]["provenance"]["sourceMode"] == "public_listening"
    assert detail["classification"]["summary"] == "Repeated shipping damage"
    assert detail["route"]["owner"] == "@retail-ops"


def test_signal_source_aliases_normalize_to_x(client, seeded_route):
    memory = SqlMemory()
    with memory.session() as session:
        signal = session.get(SignalRow, seeded_route["signal_id"])
        signal.source = "x_public"
        session.commit()

    response = client.get("/api/signals", params={"source": "twitter", "period": "qtd"})

    assert response.status_code == 200
    assert response.json()["signals"][0]["signal"]["canonicalPlatform"] == "x"
    assert response.json()["signals"][0]["signal"]["contentKind"] == "post"


def test_comment_signal_projects_parent_context_metrics_and_path(client, seeded_route):
    memory = SqlMemory()
    with memory.session() as session:
        signal = session.get(SignalRow, seeded_route["signal_id"])
        signal.source = "instagram"
        signal.raw_metadata = {
            "content_kind": "comment",
            "path": "mention_comments",
            "likes": 1800,
            "reply_count": 93,
            "parent_url": "https://instagram.com/p/parent",
            "parent_author_handle": "@acme",
            "parent_excerpt": "New look. Same product.",
        }
        session.commit()

    signal = client.get(f"/api/signals/{seeded_route['signal_id']}").json()["signal"]

    assert signal["contentKind"] == "comment"
    assert signal["metrics"] == {
        "metricType": "observed_public", "views": None, "plays": None,
        "likes": 1800, "replies": 93, "comments": None, "shares": None,
        "reposts": None, "upvotes": None,
    }
    assert signal["parentContext"]["contentKind"] == "post"
    assert signal["parentContext"]["excerpt"] == "New look. Same product."
    assert signal["provenance"]["path"] == "mention_comments"


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


def test_exported_openapi_schema_matches_react_client_base_path():
    schema = client_openapi_schema()

    assert schema["servers"] == [{"url": "/api", "description": "Base API path"}]
    assert "/brands" in schema["paths"]
    assert "/routes/{routeId}/reroute" in schema["paths"]
    assert "/workflows/{workflowId}" in schema["paths"]
    workflow = schema["components"]["schemas"]["WorkflowJob"]["properties"]
    assert "resultSummary" in workflow
    result = schema["components"]["schemas"]["PublicListeningResultSummary"]["properties"]
    assert {"effectiveSignalCaps", "sourcesTruncatedCount"} <= result.keys()
    signal = schema["components"]["schemas"]["Signal"]["properties"]
    assert {"contentKind", "metrics", "parentContext", "provenance"} <= signal.keys()
    assert "/api/brands" not in schema["paths"]
    assert "/api/v1/brands" not in schema["paths"]
