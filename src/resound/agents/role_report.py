"""Role report agent over stored public-listening data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from resound.agents.runtime import AgentRuntime
from resound.agents.tools import AgentToolContext, record_agent_note, search_signals
from resound.memory import SqlMemory
from resound.reports import ReportTemplate
from resound.tenancy import TenantContext


@dataclass(frozen=True)
class ReportSectionDraft:
    title: str
    body: str
    citation_ids: list[int]


@dataclass(frozen=True)
class RoleReportDraft:
    role: str
    timeframe: str
    sections: list[ReportSectionDraft]
    citations: list[int]
    low_data: bool
    source_freshness: dict[str, str | None]
    agent_session_id: int


class RoleReportAgent:
    def __init__(self, memory: SqlMemory):
        self.memory = memory

    def generate(
        self,
        *,
        tenant: TenantContext,
        brand_id: int,
        brand_slug: str,
        template: ReportTemplate,
        timeframe: str,
    ) -> RoleReportDraft:
        session_id = self.memory.create_agent_session(
            organization_id=tenant.organization_id,
            brand_id=brand_id,
            agent_type="role_report_analyst",
                user_goal=f"Generate {template.role} report for {brand_slug} ({timeframe})",
        )
        context = AgentToolContext(
            memory=self.memory,
            tenant=tenant,
            brand_slug=brand_slug,
            agent_session_id=session_id,
        )
        runtime = AgentRuntime.linear(
            [
                (
                    "retrieve_report_evidence",
                    lambda state: _retrieve_report_evidence(context, state),
                ),
                ("draft_role_report", lambda state: _draft_role_report(context, state)),
            ]
        )
        state = runtime.invoke(
            {
                "template": template,
                "timeframe": timeframe,
                "brand_id": brand_id,
                "brand_slug": brand_slug,
            },
        )
        self.memory.update_agent_session_status(session_id, "completed")
        return RoleReportDraft(
            role=template.role,
            timeframe=timeframe,
            sections=state["sections"],
            citations=state["citations"],
            low_data=state["low_data"],
            source_freshness=_source_freshness(self.memory, tenant.organization_id, brand_id),
            agent_session_id=session_id,
        )


def _retrieve_report_evidence(context: AgentToolContext, state: dict) -> dict:
    signals = search_signals(context, query=None, limit=10)
    return {**state, "signals": signals}


def _draft_role_report(context: AgentToolContext, state: dict) -> dict:
    template = state["template"]
    signals = state["signals"]
    citations = [signal.id for signal in signals[:10]]
    low_data = len(signals) == 0
    evidence = signals[0].content if signals else "No matching stored signals were found."
    caveat = " Low-data caveat: evidence is thin." if low_data else ""
    sections = [
        ReportSectionDraft(
            title=title,
            body=f"{title}: {evidence}{caveat}",
            citation_ids=citations[:3],
        )
        for title in template.sections
    ]
    record_agent_note(
        context,
        tool_name="generate_role_report",
        input_json={
            "role": template.role,
            "timeframe": state["timeframe"],
            "brand_slug": state["brand_slug"],
        },
        output_json={"section_count": len(sections), "citation_count": len(citations)},
    )
    return {**state, "sections": sections, "citations": citations, "low_data": low_data}


def _source_freshness(
    memory: SqlMemory,
    organization_id: int,
    brand_id: int,
) -> dict[str, str | None]:
    freshness: dict[str, str | None] = {
        "generated_from_stored_data_at": datetime.now(tz=UTC).isoformat()
    }
    for row in memory.list_source_health(organization_id, brand_id):
        freshness[f"{row.source_type}_status"] = row.status
        freshness[f"{row.source_type}_last_success_at"] = (
            row.last_success_at.isoformat() if row.last_success_at else None
        )
        if row.error_message:
            freshness[f"{row.source_type}_error"] = row.error_message
    return freshness
