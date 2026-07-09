from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resound.api.app import create_app
from resound.api.dependencies import get_workflow_starter, reset_memory_cache
from resound.memory import SqlMemory
from resound.social import ListeningProfile
from resound.workflows.client import WorkflowStartResult


class FakeWorkflowStarter:
    async def start_public_listening_sync(self, *, workflow_id: str, request):
        return WorkflowStartResult(
            workflow_id=workflow_id,
            run_id="run-public",
            task_queue="test-q",
        )

    async def start_report_generation(self, *, workflow_id: str, request):
        return WorkflowStartResult(
            workflow_id=workflow_id,
            run_id="run-report",
            task_queue="test-q",
        )

    async def start_listening_profile_setup(self, *, workflow_id: str, request):
        return WorkflowStartResult(workflow_id=workflow_id, run_id="run-setup", task_queue="test-q")


@pytest.fixture
def listening_client(tmp_path, monkeypatch):
    db_path = tmp_path / "listening-api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RESOUND_REQUIRE_TENANT_HEADER", "true")
    reset_memory_cache()
    app = create_app()
    app.dependency_overrides[get_workflow_starter] = lambda: FakeWorkflowStarter()
    yield TestClient(app)
    app.dependency_overrides.clear()
    reset_memory_cache()


def test_start_listening_setup_returns_workflow_job(listening_client):
    memory = SqlMemory()
    org = memory.ensure_organization("org-a", "Org A")
    memory.ensure_brand(org, "acme", "Acme")

    response = listening_client.post(
        "/api/listening-profiles/setup",
        json={"brandId": "acme", "brandNames": ["Acme"], "productNames": ["Checkout"]},
        headers={"X-Resound-Organization": "org-a"},
    )

    assert response.status_code == 202
    assert response.json()["workflowType"] == "ListeningProfileSetupWorkflow"
    assert response.json()["runId"] == "run-setup"


def test_accepting_suggestion_updates_profile_and_revision_audit(listening_client):
    memory = SqlMemory()
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    profile_id = memory.save_listening_profile(
        organization_id=org,
        brand_id=brand.id,
        profile=ListeningProfile(brand_slug="acme", brand_names=["Acme"], enabled_sources=[]),
    )
    suggestion_id = memory.create_listening_profile_suggestion(
        profile_id=profile_id,
        suggestion_type="keyword",
        value="checkout errors",
        reason="Common customer phrasing",
    )

    response = listening_client.patch(
        f"/api/listening-profiles/suggestions/{suggestion_id}",
        json={"decision": "accept"},
        headers={"X-Resound-Organization": "org-a"},
    )
    profile = memory.get_listening_profile(
        organization_id=org,
        brand_id=brand.id,
        brand_slug="acme",
    )
    revisions = memory.list_listening_profile_revisions(profile_id)

    assert response.status_code == 200
    assert "checkout errors" in profile.keywords
    assert revisions[-1].field_name == "keywords"
