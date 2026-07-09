from __future__ import annotations

from datetime import UTC, datetime

from resound.agents.tools import AgentToolContext, search_signals
from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.tenancy import TenantContext


def test_search_signals_is_tenant_scoped_and_audited(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'agents.db'}")
    org_a = memory.ensure_organization("org-a", "Org A")
    org_b = memory.ensure_organization("org-b", "Org B")
    brand_a = memory.ensure_brand(org_a, "acme", "Acme")
    brand_b = memory.ensure_brand(org_b, "acme", "Acme B")
    memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="a1",
            content="Acme pricing complaint",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org_a,
        brand_id=brand_a.id,
    )
    memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="b1",
            content="Other tenant complaint",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org_b,
        brand_id=brand_b.id,
    )
    context = AgentToolContext(
        memory=memory,
        tenant=TenantContext(org_a, "org-a", team_id=None, user_id=None),
        brand_slug="acme",
        agent_session_id=memory.create_agent_session(
            organization_id=org_a,
            brand_id=brand_a.id,
            agent_type="memory_analyst",
            user_goal="Find pricing complaints",
        ),
    )

    results = search_signals(context, query="pricing")
    steps = memory.list_agent_steps(context.agent_session_id)

    assert [result.content for result in results] == ["Acme pricing complaint"]
    assert steps[-1].tool_name == "search_signals"
    assert steps[-1].status == "succeeded"
