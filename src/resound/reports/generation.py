"""Report generation workflow activity helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from resound.agents.role_report import RoleReportAgent, RoleReportDraft
from resound.memory import SqlMemory
from resound.reports import role_template
from resound.reports.verification import verify_report_draft
from resound.tenancy import TenantContext
from resound.workflows.temporal_compat import activity, workflow


@dataclass(frozen=True)
class ReportGenerationRequest:
    tenant: TenantContext
    brand_id: int
    brand_slug: str
    report_config_id: int | None
    role: str
    timeframe: str
    workflow_job_id: int | None = None


@dataclass(frozen=True)
class ReportGenerationResult:
    report_run_id: int
    status: str


def generate_report(
    request: ReportGenerationRequest,
    *,
    memory: SqlMemory | None = None,
) -> ReportGenerationResult:
    memory = memory or SqlMemory()
    if request.workflow_job_id is not None:
        memory.record_workflow_event(
            workflow_job_id=request.workflow_job_id,
            stage="report_generation_started",
            status="running",
            event_metadata={"role": request.role, "timeframe": request.timeframe},
        )
    template = role_template(request.role)
    draft = RoleReportAgent(memory).generate(
        tenant=request.tenant,
        brand_id=request.brand_id,
        brand_slug=request.brand_slug,
        template=template,
        timeframe=request.timeframe,
    )
    markdown = export_report_markdown(draft)
    rows = memory.list_signals_for_tenant(request.tenant, brand_slug=request.brand_slug)
    rows_by_id = {row.id: row for row in rows}
    verification = verify_report_draft(
        draft,
        template=template,
        allowed_signal_ids=set(rows_by_id),
    )
    source_freshness = {
        **draft.source_freshness,
        "verification_status": verification.status,
        "verification_issues": verification.issues,
    }
    run_id = memory.create_report_run(
        report_config_id=request.report_config_id,
        organization_id=request.tenant.organization_id,
        brand_id=request.brand_id,
        team_id=request.tenant.team_id,
        role=template.role,
        timeframe=request.timeframe,
        status=verification.status,
        source_freshness=source_freshness,
        sections=[section.__dict__ for section in draft.sections],
        summary=draft.sections[0].body if draft.sections else "",
        markdown=markdown,
        internal_usefulness_rating=verification.internal_usefulness_rating,
    )
    for section in draft.sections:
        for signal_id in section.citation_ids:
            signal = rows_by_id.get(signal_id)
            if signal is None:
                continue
            memory.save_report_citation(
                report_run_id=run_id,
                signal_id=signal.id,
                section_title=section.title,
                quote=signal.content[:280],
                source=signal.source,
                full_text=signal.content,
            )
    if request.workflow_job_id is not None:
        memory.record_workflow_event(
            workflow_job_id=request.workflow_job_id,
            stage="report_generation_completed",
            status=verification.status,
            event_metadata={"report_run_id": run_id, "citation_count": len(draft.citations)},
        )
    return ReportGenerationResult(report_run_id=run_id, status=verification.status)


def export_report_markdown(draft: RoleReportDraft) -> str:
    title = draft.role.title()
    parts = [f"# {title} Report", ""]
    for section in draft.sections:
        parts.extend([f"## {section.title}", section.body, ""])
    return "\n".join(parts).strip() + "\n"


@activity.defn
async def generate_report_activity(request: ReportGenerationRequest) -> ReportGenerationResult:
    return generate_report(request)


@workflow.defn
class ReportGenerationWorkflow:
    @workflow.run
    async def run(self, request: ReportGenerationRequest) -> ReportGenerationResult:
        return await workflow.execute_activity(
            generate_report_activity,
            request,
            start_to_close_timeout=timedelta(minutes=10),
        )
