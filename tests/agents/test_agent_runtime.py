from __future__ import annotations

from datetime import UTC, datetime

from resound.agents.runtime import AgentRuntime
from resound.agents.tools import AgentToolContext, get_signal
from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.tenancy import TenantContext


def test_agent_runtime_compiles_langgraph_linear_graph():
    runtime = AgentRuntime.linear([("set_value", lambda state: {**state, "value": 42})])

    result = runtime.invoke({})

    assert result["value"] == 42
    assert runtime.graph is not None


def test_get_signal_missing_tenant_scope_records_recoverable_tool_error(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'agent-runtime.db'}")
    org_a = memory.ensure_organization("org-a", "Org A")
    org_b = memory.ensure_organization("org-b", "Org B")
    brand_a = memory.ensure_brand(org_a, "acme", "Acme")
    brand_b = memory.ensure_brand(org_b, "acme", "Acme B")
    hidden_signal_id = memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="b1",
            content="Other tenant signal",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org_b,
        brand_id=brand_b.id,
    )
    session_id = memory.create_agent_session(
        organization_id=org_a,
        brand_id=brand_a.id,
        agent_type="memory_analyst",
        user_goal="Inspect signal",
    )
    context = AgentToolContext(
        memory=memory,
        tenant=TenantContext(org_a, "org-a", team_id=None, user_id=None),
        brand_slug="acme",
        agent_session_id=session_id,
    )

    result = get_signal(context, hidden_signal_id)
    steps = memory.list_agent_steps(session_id)

    assert result is None
    assert steps[-1].tool_name == "get_signal"
    assert steps[-1].status == "failed"
    assert steps[-1].error_message == "Signal not found in tenant scope"
