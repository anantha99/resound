"""Listening setup agent graph helpers."""

from __future__ import annotations

from dataclasses import dataclass

from resound.agents.runtime import AgentRuntime
from resound.agents.tools import AgentToolContext, record_agent_note
from resound.social import V1_PUBLIC_SOURCE_TYPES


@dataclass(frozen=True)
class ListeningSetupSuggestionSet:
    keywords: list[str]
    sources: list[str]


class ListeningSetupAgent:
    def propose(
        self,
        *,
        context: AgentToolContext,
        brand_names: list[str],
        product_names: list[str],
        competitor_names: list[str],
    ) -> ListeningSetupSuggestionSet:
        runtime = AgentRuntime.linear(
            [("propose_listening_terms", lambda state: _propose_listening_terms(context, state))]
        )
        state = runtime.invoke(
            {
                "brand_names": brand_names,
                "product_names": product_names,
                "competitor_names": competitor_names,
            }
        )
        return ListeningSetupSuggestionSet(keywords=state["keywords"], sources=state["sources"])


def _propose_listening_terms(context: AgentToolContext, state: dict) -> dict:
    keywords = sorted(
        dict.fromkeys(
            term.strip()
            for term in [
                *state.get("brand_names", []),
                *state.get("product_names", []),
                *state.get("competitor_names", []),
            ]
            if term and term.strip()
        )
    )
    sources = sorted(V1_PUBLIC_SOURCE_TYPES)
    record_agent_note(
        context,
        tool_name="propose_listening_terms",
        input_json={"brand_names": state.get("brand_names", [])},
        output_json={"keyword_count": len(keywords), "source_count": len(sources)},
    )
    return {**state, "keywords": keywords, "sources": sources}
