"""Small wrapper around LangGraph for bounded agent graphs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

AgentStep = tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]


@dataclass(frozen=True)
class AgentRuntime:
    """Compile and invoke small state graphs.

    The first implementation keeps a deterministic fallback path so product
    tools can be tested without a model or a running graph backend. When
    LangGraph is installed, callers can pass a compiled graph directly.
    """

    graph: Any | None = None
    fallback: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    @classmethod
    def linear(cls, steps: Sequence[AgentStep]) -> AgentRuntime:
        """Compile a plain LangGraph linear graph with a deterministic fallback."""
        fallback = _linear_fallback(steps)
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:
            return cls(graph=None, fallback=fallback)

        builder = StateGraph(dict)
        previous = START
        for name, fn in steps:
            builder.add_node(name, fn)
            builder.add_edge(previous, name)
            previous = name
        builder.add_edge(previous, END)
        return cls(graph=builder.compile(), fallback=fallback)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.graph is not None:
            return self.graph.invoke(state)
        if self.fallback is None:
            return state
        return self.fallback(state)


def _linear_fallback(steps: Sequence[AgentStep]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def invoke(state: dict[str, Any]) -> dict[str, Any]:
        current = dict(state)
        for _, step in steps:
            current.update(step(current))
        return current

    return invoke
