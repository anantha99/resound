from __future__ import annotations

from datetime import UTC, datetime

from resound.agents.memory_query import MemoryQueryAgent
from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.tenancy import TenantContext


def test_memory_query_agent_answers_with_signal_references(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'memory-agent.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    signal_id = memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="p1",
            content="Customers keep asking for dark mode.",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org,
        brand_id=brand.id,
    )

    answer = MemoryQueryAgent(memory).answer(
        tenant=TenantContext(org, "org-a", team_id=None, user_id=None),
        brand_slug="acme",
        question="What are customers asking for?",
    )

    assert "dark mode" in answer.answer
    assert answer.citations == [signal_id]
    assert answer.agent_session_id is not None
