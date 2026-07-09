"""Memory query agent for cited answers over stored signals."""

from __future__ import annotations

from dataclasses import dataclass

from resound.agents.runtime import AgentRuntime
from resound.agents.tools import AgentToolContext, record_agent_note, search_signals
from resound.memory import SqlMemory
from resound.tenancy import TenantContext


@dataclass(frozen=True)
class MemoryQueryAnswer:
    answer: str
    citations: list[int]
    agent_session_id: int


class MemoryQueryAgent:
    def __init__(self, memory: SqlMemory):
        self.memory = memory

    def answer(
        self,
        *,
        tenant: TenantContext,
        brand_slug: str,
        question: str,
    ) -> MemoryQueryAnswer:
        session_id = self.memory.create_agent_session(
            organization_id=tenant.organization_id,
            brand_id=None,
            agent_type="memory_analyst",
            user_goal=question,
        )
        context = AgentToolContext(
            memory=self.memory,
            tenant=tenant,
            brand_slug=brand_slug,
            agent_session_id=session_id,
        )
        runtime = AgentRuntime.linear(
            [
                ("retrieve_memory", lambda state: _retrieve_memory(context, state)),
                ("synthesize_answer", lambda state: _synthesize_answer(context, state)),
            ]
        )
        state = runtime.invoke({"question": question})
        self.memory.update_agent_session_status(session_id, "completed")
        return MemoryQueryAnswer(
            answer=state["answer"],
            citations=state["citations"],
            agent_session_id=session_id,
        )


def _retrieve_memory(
    context: AgentToolContext,
    state: dict,
) -> dict:
    signals = search_signals(context, query=None, limit=5)
    return {"signals": signals, "question": state["question"]}


def _synthesize_answer(
    context: AgentToolContext,
    state: dict,
) -> dict:
    signals = state["signals"]
    if not signals:
        record_agent_note(
            context,
            tool_name="synthesize_memory_answer",
            input_json={"question": state["question"], "signal_count": 0},
            output_json={"citation_count": 0},
        )
        return {"answer": "No stored signals matched this question.", "citations": []}
    excerpts = "; ".join(signal.content for signal in signals)
    citations = [signal.id for signal in signals]
    record_agent_note(
        context,
        tool_name="synthesize_memory_answer",
        input_json={"question": state["question"], "signal_count": len(signals)},
        output_json={"citation_count": len(citations)},
    )
    return {
        "answer": f"Stored customer voice includes: {excerpts}",
        "citations": citations,
    }
