from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resound.api.app import create_app
from resound.api.dependencies import reset_memory_cache
from resound.memory import SqlMemory


@pytest.fixture
def agent_client(tmp_path, monkeypatch):
    db_path = tmp_path / "agent-api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RESOUND_REQUIRE_TENANT_HEADER", "true")
    reset_memory_cache()
    yield TestClient(create_app())
    reset_memory_cache()


def test_agent_sessions_are_visible_to_owning_tenant(agent_client):
    memory = SqlMemory()
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    session_id = memory.create_agent_session(
        organization_id=org,
        brand_id=brand.id,
        agent_type="memory_analyst",
        user_goal="What changed this week?",
        status="completed",
    )

    response = agent_client.get(
        "/api/agents/sessions",
        headers={"X-Resound-Organization": "org-a"},
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == session_id
    assert response.json()[0]["agentType"] == "memory_analyst"
