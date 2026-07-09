"""Pattern analyst graph over stored signals."""

from __future__ import annotations

from dataclasses import dataclass

from resound.agents.runtime import AgentRuntime
from resound.agents.tools import AgentToolContext, record_agent_note, search_signals


@dataclass(frozen=True)
class PatternInsight:
    name: str
    signal_ids: list[int]
    summary: str


class PatternAnalysisAgent:
    def analyze(self, context: AgentToolContext) -> list[PatternInsight]:
        runtime = AgentRuntime.linear(
            [
                (
                    "retrieve_pattern_evidence",
                    lambda state: _retrieve_pattern_evidence(context, state),
                ),
                ("summarize_patterns", lambda state: _summarize_patterns(context, state)),
            ]
        )
        state = runtime.invoke({})
        return state["patterns"]


def _retrieve_pattern_evidence(context: AgentToolContext, state: dict) -> dict:
    return {**state, "signals": search_signals(context, query=None, limit=50)}


def _summarize_patterns(context: AgentToolContext, state: dict) -> dict:
    by_source: dict[str, list[int]] = {}
    for signal in state["signals"]:
        by_source.setdefault(signal.source, []).append(signal.id)
    patterns = [
        PatternInsight(
            name=f"{source} cluster",
            signal_ids=ids,
            summary=f"{len(ids)} stored signals from {source} need review.",
        )
        for source, ids in sorted(by_source.items())
    ]
    record_agent_note(
        context,
        tool_name="summarize_patterns",
        output_json={"pattern_count": len(patterns)},
    )
    return {**state, "patterns": patterns}
