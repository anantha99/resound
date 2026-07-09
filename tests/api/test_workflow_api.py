from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from resound.api.app import create_app
from resound.api.dependencies import get_workflow_starter, reset_memory_cache
from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.workflows.client import WorkflowStartResult


class FakeWorkflowStarter:
    def __init__(self):
        self.calls: list[tuple[str, str, object]] = []

    async def start_public_listening_sync(self, *, workflow_id: str, request):
        self.calls.append(("public", workflow_id, request))
        return WorkflowStartResult(
            workflow_id=workflow_id,
            run_id="run-public",
            task_queue="test-q",
        )

    async def start_report_generation(self, *, workflow_id: str, request):
        self.calls.append(("report", workflow_id, request))
        return WorkflowStartResult(
            workflow_id=workflow_id,
            run_id="run-report",
            task_queue="test-q",
        )


@pytest.fixture
def production_client(tmp_path, monkeypatch):
    db_path = tmp_path / "workflow-api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RESOUND_REQUIRE_TENANT_HEADER", "true")
    reset_memory_cache()
    app = create_app()
    starter = FakeWorkflowStarter()
    app.dependency_overrides[get_workflow_starter] = lambda: starter
    client = TestClient(app)
    client.workflow_starter = starter
    yield client
    app.dependency_overrides.clear()
    reset_memory_cache()


def _seed_brand() -> tuple[int, int]:
    memory = SqlMemory()
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    return org, brand.id


def test_source_sync_command_returns_workflow_identity_without_blocking(production_client):
    _seed_brand()

    response = production_client.post(
        "/api/workflows/source-sync",
        json={"brandId": "acme"},
        headers={"X-Resound-Organization": "org-a"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["runId"] == "run-public"
    assert body["workflowType"] == "PublicListeningSyncWorkflow"
    assert body["workflowId"].startswith("public-listening-sync-acme-")
    assert production_client.workflow_starter.calls[0][0] == "public"


def test_report_generation_command_starts_temporal_workflow(production_client):
    _seed_brand()

    response = production_client.post(
        "/api/reports/runs",
        json={"brandId": "acme", "role": "product", "timeframe": "7d"},
        headers={"X-Resound-Organization": "org-a"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["workflowType"] == "ReportGenerationWorkflow"
    assert body["runId"] == "run-report"
    assert production_client.workflow_starter.calls[-1][0] == "report"


def test_report_templates_and_runs_are_tenant_scoped(production_client):
    org, brand_id = _seed_brand()
    memory = SqlMemory()
    config_id = memory.save_report_config(
        organization_id=org,
        brand_id=brand_id,
        team_id=None,
        role="founder",
        name="Founder Weekly",
    )
    run_id = memory.create_report_run(
        report_config_id=config_id,
        organization_id=org,
        brand_id=brand_id,
        team_id=None,
        role="founder",
        timeframe="7d",
        status="held_for_review",
        sections=[],
        markdown="# Founder Report\n",
    )

    templates = production_client.get(
        "/api/reports/templates",
        headers={"X-Resound-Organization": "org-a"},
    )
    runs = production_client.get(
        "/api/reports/runs",
        headers={"X-Resound-Organization": "org-a"},
    )

    assert templates.status_code == 200
    assert {template["role"] for template in templates.json()} >= {"founder", "product"}
    assert runs.status_code == 200
    assert [run["id"] for run in runs.json()] == [run_id]


def test_public_feed_is_delayed_capped_and_non_exportable(production_client):
    org, brand_id = _seed_brand()
    memory = SqlMemory()
    for idx in range(3):
        memory.record_signal(
            "acme",
            RawSignal(
                source="reddit",
                external_id=f"pub-{idx}",
                content=f"Visible public item {idx}",
                posted_at=datetime(2026, 6, 1, tzinfo=UTC),
                raw_metadata={"public_feed_visible": True},
            ),
            organization_id=org,
            brand_id=brand_id,
        )
    memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="hidden",
            content="Hidden item",
            posted_at=datetime(2026, 6, 1, tzinfo=UTC),
            raw_metadata={"public_feed_visible": False},
        ),
        organization_id=org,
        brand_id=brand_id,
    )

    response = production_client.get("/api/public/feed", params={"brandId": "acme", "limit": 2})
    export = production_client.get("/api/public/feed/export")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2
    assert all("Hidden" not in item["content"] for item in response.json()["items"])
    assert export.status_code == 404


def test_public_feed_moderation_hides_shows_and_audits_items(production_client):
    org, brand_id = _seed_brand()
    memory = SqlMemory()
    signal_id = memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="moderated",
            content="Moderated public item",
            posted_at=datetime(2026, 6, 1, tzinfo=UTC),
            raw_metadata={"public_feed_visible": True},
        ),
        organization_id=org,
        brand_id=brand_id,
    )

    hide = production_client.patch(
        f"/api/public/feed/items/{signal_id}/moderation",
        json={"action": "hide", "reason": "Contains private info", "actor": "operator"},
        headers={"X-Resound-Organization": "org-a"},
    )
    hidden_feed = production_client.get("/api/public/feed", params={"brandId": "acme"})
    show = production_client.patch(
        f"/api/public/feed/items/{signal_id}/moderation",
        json={"action": "show", "actor": "operator"},
        headers={"X-Resound-Organization": "org-a"},
    )
    visible_feed = production_client.get("/api/public/feed", params={"brandId": "acme"})
    no_export = production_client.patch(
        f"/api/public/feed/items/{signal_id}/moderation",
        json={"action": "no_export", "actor": "operator"},
        headers={"X-Resound-Organization": "org-a"},
    )
    events = memory.list_public_feed_moderation_events(signal_id)

    assert hide.status_code == 200
    assert hide.json()["action"] == "hide"
    assert hidden_feed.json()["items"] == []
    assert show.status_code == 200
    assert visible_feed.json()["items"][0]["id"] == signal_id
    assert visible_feed.json()["exportAvailable"] is False
    assert no_export.status_code == 200
    assert [event.action for event in events] == ["hide", "show", "no_export"]


def test_internal_errors_return_sanitized_problem_details(tmp_path, monkeypatch):
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{tmp_path / 'errors.db'}")
    reset_memory_cache()
    app = create_app()
    router = APIRouter()

    @router.get("/explode")
    def explode():
        raise RuntimeError("secret-token-123")

    app.include_router(router, prefix="/api")
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/explode")

    assert response.status_code == 500
    assert response.json()["detail"] == "An unexpected error occurred."
    assert "secret-token" not in response.text
