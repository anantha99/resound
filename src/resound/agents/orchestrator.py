"""Bounded agentic orchestrator graph."""

from __future__ import annotations

from dataclasses import dataclass

from resound.agents.runtime import AgentRuntime
from resound.agents.tools import AgentToolContext, record_agent_note


@dataclass(frozen=True)
class OrchestratorResult:
    status: str
    steps: list[str]


class AgenticOrchestrator:
    def run(self, *, context: AgentToolContext, goal: str) -> OrchestratorResult:
        runtime = AgentRuntime.linear(
            [
                ("plan_goal", lambda state: _plan_goal(context, state)),
                ("finish_goal", lambda state: _finish_goal(context, state)),
            ]
        )
        state = runtime.invoke({"goal": goal})
        return OrchestratorResult(status=state["status"], steps=state["steps"])


def _plan_goal(context: AgentToolContext, state: dict) -> dict:
    steps = ["inspect stored signals", "summarize findings", "request approval before mutations"]
    record_agent_note(
        context,
        tool_name="plan_goal",
        input_json={"goal": state["goal"]},
        output_json={"step_count": len(steps)},
    )
    return {**state, "steps": steps}


def _finish_goal(context: AgentToolContext, state: dict) -> dict:
    record_agent_note(
        context,
        tool_name="finish_goal",
        output_json={"status": "completed"},
    )
    return {**state, "status": "completed"}
