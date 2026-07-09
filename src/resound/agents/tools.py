"""Audited domain tools exposed to agents."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from resound.memory import SignalRow, SqlMemory
from resound.tenancy import TenantContext


@dataclass(frozen=True)
class AgentToolContext:
    memory: SqlMemory
    tenant: TenantContext
    brand_slug: str
    agent_session_id: int


@dataclass(frozen=True)
class SignalSearchResult:
    id: int
    source: str
    content: str
    posted_at: datetime


def search_signals(
    context: AgentToolContext,
    *,
    query: str | None = None,
    limit: int = 20,
) -> list[SignalSearchResult]:
    rows = context.memory.list_signals_for_tenant(context.tenant, brand_slug=context.brand_slug)
    if query:
        needle = query.lower()
        rows = [row for row in rows if needle in row.content.lower()]
    results = [_signal_result(row) for row in rows[:limit]]
    context.memory.record_agent_step(
        agent_session_id=context.agent_session_id,
        tool_name="search_signals",
        input_json={"query": query, "limit": limit, "brand_slug": context.brand_slug},
        output_json={"count": len(results), "signal_ids": [result.id for result in results]},
    )
    return results


def get_signal(context: AgentToolContext, signal_id: int) -> SignalSearchResult | None:
    rows = context.memory.list_signals_for_tenant(context.tenant, brand_slug=context.brand_slug)
    for row in rows:
        if row.id == signal_id:
            result = _signal_result(row)
            context.memory.record_agent_step(
                agent_session_id=context.agent_session_id,
                tool_name="get_signal",
                input_json={"signal_id": signal_id},
                output_json={"found": True},
            )
            return result
    context.memory.record_agent_step(
        agent_session_id=context.agent_session_id,
        tool_name="get_signal",
        input_json={"signal_id": signal_id},
        output_json={"found": False},
        status="failed",
        error_message="Signal not found in tenant scope",
    )
    return None


def record_agent_note(
    context: AgentToolContext,
    *,
    tool_name: str,
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    status: str = "succeeded",
    error_message: str | None = None,
) -> None:
    context.memory.record_agent_step(
        agent_session_id=context.agent_session_id,
        tool_name=tool_name,
        input_json=input_json or {},
        output_json=output_json or {},
        status=status,
        error_message=error_message,
    )


def _signal_result(row: SignalRow) -> SignalSearchResult:
    return SignalSearchResult(
        id=row.id,
        source=row.source,
        content=row.content,
        posted_at=row.posted_at,
    )
