from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from resound.api.app import create_app
from resound.api.dependencies import reset_memory_cache
from resound.gateway import LLMResponse
from resound.memory import SqlMemory


@pytest.fixture
def operations_client(tmp_path, monkeypatch):
    db_path = tmp_path / "operations-api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RESOUND_REQUIRE_TENANT_HEADER", "true")
    reset_memory_cache()
    yield TestClient(create_app())
    reset_memory_cache()


def test_readiness_returns_degraded_when_optional_services_are_missing(operations_client):
    response = operations_client.get("/api/readiness")

    assert response.status_code == 200
    assert response.json()["status"] in {"ok", "degraded"}
    assert {check["name"] for check in response.json()["checks"]} >= {
        "database",
        "temporal",
        "openrouter",
        "apify",
    }


def test_source_health_telemetry_and_evaluation_are_tenant_scoped(operations_client):
    memory = SqlMemory()
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    other_org = memory.ensure_organization("org-b", "Org B")
    other_brand = memory.ensure_brand(other_org, "acme", "Acme B")
    memory.record_source_health(
        organization_id=org,
        brand_id=brand.id,
        source_type="reddit",
        provider="apify",
        status="failed",
        error_message="rate limited",
        checked_at=datetime.now(tz=UTC),
    )
    memory.record_llm_call(
        brand_slug="acme",
        stage="classify",
        prompt="prompt",
        response=LLMResponse(
            content="{}",
            model_used="openrouter/test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.25,
            latency_ms=120,
        ),
        was_fallback=False,
        attempt_count=1,
        organization_id=org,
        brand_id=brand.id,
    )
    memory.record_llm_call(
        brand_slug="acme",
        stage="classify",
        prompt="prompt",
        response=LLMResponse(
            content="{}",
            model_used="openrouter/test",
            tokens_in=10,
            tokens_out=5,
            cost_usd=9.99,
            latency_ms=120,
        ),
        was_fallback=False,
        attempt_count=1,
        organization_id=other_org,
        brand_id=other_brand.id,
    )
    memory.create_report_run(
        organization_id=org,
        brand_id=brand.id,
        team_id=None,
        role="founder",
        timeframe="7d",
        status="held_for_review",
    )

    headers = {"X-Resound-Organization": "org-a"}
    health = operations_client.get(
        "/api/source-health",
        params={"brandId": "acme"},
        headers=headers,
    )
    telemetry = operations_client.get(
        "/api/telemetry/llm",
        params={"brandId": "acme", "period": "7d"},
        headers=headers,
    )
    evaluation = operations_client.get(
        "/api/evaluations/summary",
        params={"brandId": "acme", "period": "7d"},
        headers=headers,
    )

    assert health.status_code == 200
    assert health.json()[0]["status"] == "failed"
    assert health.json()[0]["canonicalSource"] == "reddit"
    assert health.json()[0]["path"] == "official_discovery"
    assert health.json()[0]["fetchedCount"] == 0
    assert telemetry.status_code == 200
    assert telemetry.json()["costs"][0]["total_cost_usd"] == 0.25
    assert evaluation.status_code == 200
    assert evaluation.json()["sourceFailureCount"] == 1
    assert evaluation.json()["reportRunsByStatus"] == {"held_for_review": 1}
