from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from resound.api.app import app
from resound.api.dependencies import reset_memory_cache
from resound.memory import SqlMemory
from resound.models import ActionClass, Classification, RawSignal, Route, Sentiment, Severity


@pytest.fixture
def tenant_client(tmp_path, monkeypatch):
    db_path = tmp_path / "tenant-api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RESOUND_REQUIRE_TENANT_HEADER", "true")
    reset_memory_cache()
    yield TestClient(app)
    reset_memory_cache()


def test_missing_tenant_context_is_rejected_in_production_mode(tenant_client):
    response = tenant_client.get("/api/brands")

    assert response.status_code == 401


def test_brand_list_uses_tenant_context_when_header_is_present(tenant_client):
    memory = SqlMemory()
    org = memory.ensure_organization("org-a", "Org A")
    memory.ensure_brand(org, "acme", "Acme")
    other_org = memory.ensure_organization("org-b", "Org B")
    memory.ensure_brand(other_org, "other", "Other")

    response = tenant_client.get("/api/brands", headers={"X-Resound-Organization": "org-a"})

    assert response.status_code == 200
    assert [brand["slug"] for brand in response.json()] == ["acme"]


def test_signal_route_and_pattern_reads_are_tenant_scoped(tenant_client):
    memory = SqlMemory()
    org_a = memory.ensure_organization("org-a", "Org A")
    org_b = memory.ensure_organization("org-b", "Org B")
    brand_a = memory.ensure_brand(org_a, "acme", "Acme")
    brand_b = memory.ensure_brand(org_b, "acme", "Acme B")
    route_a = _seed_classified_route(memory, org_a, brand_a.id, "a1", "Org A checkout complaint")
    route_b = _seed_classified_route(memory, org_b, brand_b.id, "b1", "Org B private complaint")

    signals = tenant_client.get(
        "/api/signals",
        params={"brandId": "acme", "period": "qtd"},
        headers={"X-Resound-Organization": "org-a"},
    )
    hidden_signal = tenant_client.get(
        f"/api/signals/{route_b['signal_id']}",
        headers={"X-Resound-Organization": "org-a"},
    )
    routes = tenant_client.get(
        "/api/routes",
        params={"brandId": "acme", "period": "qtd"},
        headers={"X-Resound-Organization": "org-a"},
    )
    hidden_reroute = tenant_client.patch(
        f"/api/routes/{route_b['route_id']}/reroute",
        json={"owner": "@ops"},
        headers={"X-Resound-Organization": "org-a"},
    )
    patterns = tenant_client.get(
        "/api/patterns",
        params={"brandId": "acme"},
        headers={"X-Resound-Organization": "org-a"},
    )

    assert signals.status_code == 200
    assert signals.json()["total"] == 1
    assert signals.json()["signals"][0]["signal"]["id"] == route_a["signal_id"]
    assert hidden_signal.status_code == 404
    assert routes.status_code == 200
    assert [route["id"] for route in routes.json()] == [route_a["route_id"]]
    assert hidden_reroute.status_code == 404
    assert patterns.status_code == 200
    assert patterns.json()[0]["brandId"] == "acme"


def _seed_classified_route(
    memory: SqlMemory,
    organization_id: int,
    brand_id: int,
    external_id: str,
    content: str,
) -> dict[str, int]:
    signal_id = memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id=external_id,
            content=content,
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=organization_id,
        brand_id=brand_id,
    )
    classification_id = memory.record_classification(
        signal_id,
        Classification(
            is_about_brand=True,
            area="product",
            subarea="checkout",
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.HIGH,
            action_class=ActionClass.SPRINT,
            summary="Checkout issue",
            confidence=0.8,
        ),
    )
    route_id = memory.record_route(
        signal_id,
        classification_id,
        Route(owner_id="@support"),
    )
    return {"signal_id": signal_id, "route_id": route_id}
