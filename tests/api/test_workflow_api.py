from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from resound.api.app import create_app
from resound.api.dependencies import get_workflow_starter, reset_memory_cache
from resound.config import BrandConfig
from resound.memory import SqlMemory, WorkflowJobRow
from resound.models import RawSignal
from resound.social.config import approval_envelope_fingerprint
from resound.workflows.client import WorkflowStartResult
from resound.workflows.result_persistence import bounded_result_summary


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
    monkeypatch.setattr("resound.api.routes.workflows.load_brand_config", lambda _slug: _brand())
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


def _brand() -> BrandConfig:
    source = {
        "enabled": True,
        "preflight_required": False,
        "manifest_version": "test-1",
        "paths": {
            "official_discovery": {
                "enabled": True,
                "selectors": [{"kind": "url", "value": "https://acme.test"}],
            },
            "mention_discovery": {
                "enabled": True,
                "selectors": [{"kind": "search", "value": "Acme"}],
            },
        },
        "limits": {
            "max_signals_per_source": 100,
            "max_items_per_path": 25,
            "max_parents_per_path": 10,
            "max_comments_per_parent": 5,
            "max_comments_per_path": 25,
            "max_comments_per_source": 50,
            "max_runs_per_source": 10,
            "max_cost_usd_per_source": "1.00",
            "page_size": 100,
            "deadline_reserve_seconds": 30,
        },
        "provider_evidence": [
            {
                "source": "reddit", "path": path, "actor_role": "discovery",
                "actor_id": "solidcode/reddit-scraper",
                "build_id": "LxJ3Vm9RHSEJcQEYK", "build_number": "1.1.31",
                "provider_declared_input_schema_reference": "provider://input",
                "provider_declared_input_schema_sha256": "a" * 64,
                "provider_declared_output_schema_reference": "provider://output",
                "provider_declared_output_schema_sha256": "b" * 64,
                "fixture_derived_shape_reference": "fixtures/reddit.json",
                "fixture_derived_shape_sha256": "c" * 64,
                "canary_required": False, "charge_quantum_usd": "0.001",
                "minimum_call_charge_usd": "0.01",
                "conservative_request_cost_usd": "0.05",
            }
            for path in ("official_discovery", "mention_discovery")
        ],
    }
    source["approved_envelope_fingerprint"] = approval_envelope_fingerprint(source)
    return BrandConfig(
        slug="acme", sources={"reddit": source}, understanding="Acme context",
        routing={"rules": []}, people={"people": {}},
    )


def test_source_sync_command_returns_workflow_identity_without_blocking(production_client):
    _seed_brand()

    response = production_client.post(
        "/api/workflows/source-sync",
        json={
            "brandId": "acme",
            "selectedSources": ["reddit"],
            "selectedPaths": [{"source": "reddit", "paths": ["official_discovery"]}],
            "limits": {"maxSignalsPerSource": 9},
        },
        headers={"X-Resound-Organization": "org-a"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["runId"] == "run-public"
    assert body["workflowType"] == "PublicListeningSyncWorkflow"
    assert body["workflowId"].startswith(f"public-listening-sync:org:{_seed_brand()[0]}:")
    assert body["resultSummary"] is None
    assert body["requestFingerprintSummary"]["reddit"]["value"]
    assert production_client.workflow_starter.calls[0][0] == "public"
    request = production_client.workflow_starter.calls[0][2]
    assert request.sources[0].limits.max_signals_per_source == 9


def test_source_sync_rejects_upward_signal_cap_and_missing_tenant(production_client):
    _seed_brand()
    payload = {
        "brandId": "acme",
        "selectedSources": ["reddit"],
        "limits": {"maxSignalsPerSource": 101},
    }

    missing = production_client.post("/api/workflows/source-sync", json=payload)
    rejected = production_client.post(
        "/api/workflows/source-sync", json=payload,
        headers={"X-Resound-Organization": "org-a"},
    )

    assert missing.status_code == 401
    assert rejected.status_code == 422
    assert "may only lower" in rejected.json()["detail"]


def test_repeated_start_unknown_reconciles_preserved_job_without_creating_another(
    production_client,
):
    _seed_brand()
    payload = {
        "brandId": "acme",
        "selectedSources": ["reddit"],
        "selectedPaths": [{"source": "reddit", "paths": ["official_discovery"]}],
        "limits": {"maxSignalsPerSource": 9},
    }
    headers = {"X-Resound-Organization": "org-a"}
    first = production_client.post("/api/workflows/source-sync", json=payload, headers=headers)
    workflow_id = first.json()["workflowId"]
    memory = SqlMemory()
    with Session(memory.engine) as session:
        job = session.query(WorkflowJobRow).filter_by(workflow_id=workflow_id).one()
        original_job_id = job.id
        original_snapshot = job.resolved_config_snapshot
        job.status = "start_unknown"
        session.commit()

    second = production_client.post("/api/workflows/source-sync", json=payload, headers=headers)

    assert second.status_code == 202
    assert second.json()["id"] == original_job_id
    assert second.json()["workflowId"] == workflow_id
    assert len(production_client.workflow_starter.calls) == 2
    retried_request = production_client.workflow_starter.calls[-1][2]
    assert retried_request.model_dump(mode="json") == original_snapshot
    with Session(memory.engine) as session:
        assert session.query(WorkflowJobRow).count() == 1


@pytest.mark.parametrize("terminal_status", ["completed", "partial", "failed"])
def test_workflow_retrieval_is_tenant_scoped_and_projects_bounded_results(
    production_client, terminal_status,
):
    org, brand_id = _seed_brand()
    memory = SqlMemory()
    other_org = memory.ensure_organization("org-b", "Org B")
    summary = bounded_result_summary({
        "schema_version": "1", "status": terminal_status, "selected_sources": ["reddit"],
        "selected_paths": {"reddit": ["official_discovery"]},
        "effective_signal_caps": {"reddit": 9}, "processed_count": 3,
        "sources": [{
            "source": "reddit", "platform": "reddit",
            "status": "ok" if terminal_status == "completed" else terminal_status,
            "max_signals_per_source": 9, "processed_count": 3, "cap_reached": False,
            "paths": [{
                "path": "official_discovery",
                "status": "ok" if terminal_status == "completed" else terminal_status,
                "processed_count": 3,
                "issues": [{
                    "path": "official_discovery", "code": "bounded",
                    "issue_class": "ProviderIssue", "message": "preserved",
                    "run_id": "run-1", "dataset_id": "dataset-1",
                }],
                "runs": [{
                    "path": "official_discovery", "actor_id": "owner/reddit",
                    "build_id": "build", "build_number": "1", "run_id": "run-1",
                    "requested_row_maximum": 9, "max_total_charge_usd": "0.50",
                    "usage_total_usd": "0.10", "status": "SUCCEEDED",
                    "input_schema_reference": "provider://input",
                    "output_schema_reference": "provider://output",
                    "fixture_shape_reference": "fixtures/reddit.json",
                    "dataset_ids": ["dataset-1"],
                }],
                "datasets": [{
                    "path": "official_discovery", "dataset_id": "dataset-1",
                    "run_id": "run-1", "requested_limit": 9, "fetched_count": 3,
                    "processed_count": 3, "provenance": {"provider": "apify"},
                }],
                "associations": [{
                    "path": "official_discovery",
                    "identity": {"kind": "provider_native_id", "value": "post-1"},
                    "signal_id": 1, "processing_state": "processed",
                }],
            }],
        }],
    })
    job_id = memory.create_workflow_job(
        workflow_id="bounded-job", workflow_type="PublicListeningSyncWorkflow",
        organization_id=org, brand_id=brand_id, status=terminal_status,
        request_fingerprint_summary={"reddit": {"value": "a" * 64}},
    )
    null_job = memory.create_workflow_job(
        workflow_id="running-job", workflow_type="PublicListeningSyncWorkflow",
        organization_id=org, brand_id=brand_id, status="running",
    )
    with Session(memory.engine) as session:
        job = session.get(WorkflowJobRow, job_id)
        job.result_schema_version = 1
        job.result_summary = summary
        session.commit()

    own = production_client.get(
        "/api/workflows/bounded-job", headers={"X-Resound-Organization": "org-a"},
    )
    running = production_client.get(
        "/api/workflows/running-job", headers={"X-Resound-Organization": "org-a"},
    )
    hidden = production_client.get(
        "/api/workflows/bounded-job", headers={"X-Resound-Organization": "org-b"},
    )

    assert null_job > 0 and other_org > 0
    assert own.status_code == 200
    assert own.json()["resultSummary"]["status"] == terminal_status
    assert own.json()["resultSummary"]["effectiveSignalCaps"] == {"reddit": 9}
    assert own.json()["resultSummary"]["sources"][0]["pathsTruncatedCount"] == 0
    path = own.json()["resultSummary"]["sources"][0]["paths"][0]
    assert path["runs"][0]["actorId"] == "owner/reddit"
    assert path["datasets"][0]["datasetId"] == "dataset-1"
    assert path["associations"][0]["identity"]["kind"] == "provider_native_id"
    assert running.json()["resultSummary"] is None
    assert hidden.status_code == 404


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
