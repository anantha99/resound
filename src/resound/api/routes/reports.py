from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from resound.api import schemas
from resound.api.dependencies import get_memory, get_tenant_context, get_workflow_starter
from resound.memory import SqlMemory
from resound.reports import REPORT_ROLES, role_template
from resound.reports.generation import ReportGenerationRequest
from resound.tenancy import TenantContext
from resound.workflows.client import WorkflowStarter

router = APIRouter(tags=["reports"])


@router.get("/reports/templates", operation_id="listReportTemplates")
def list_report_templates() -> list[schemas.ReportTemplate]:
    return [
        schemas.ReportTemplate(
            role=template.role,
            display_name=template.display_name,
            sections=template.sections,
        )
        for template in (role_template(role) for role in REPORT_ROLES)
    ]


@router.get("/reports/runs", operation_id="listReportRuns")
def list_report_runs(
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> list[schemas.ReportRun]:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    return [
        schemas.ReportRun(
            id=row.id,
            report_config_id=row.report_config_id,
            role=row.role,
            timeframe=row.timeframe,
            status=row.status,
            markdown=row.markdown,
            generated_at=row.generated_at.isoformat(),
        )
        for row in memory.list_report_runs_for_tenant(tenant)
    ]


@router.post(
    "/reports/runs",
    operation_id="startReportGeneration",
    response_model=schemas.WorkflowJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_report_generation(
    payload: schemas.ReportRunCreateInput,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
    starter: WorkflowStarter = Depends(get_workflow_starter),
) -> schemas.WorkflowJob:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    role_template(payload.role)
    brand_id = _brand_id_for_slug(memory, tenant, payload.brand_id)
    workflow_id = f"report-generation-{payload.brand_id}-{uuid4().hex[:12]}"
    job_id = memory.create_workflow_job(
        workflow_id=workflow_id,
        workflow_type="ReportGenerationWorkflow",
        organization_id=tenant.organization_id,
        brand_id=brand_id,
    )
    request = ReportGenerationRequest(
        tenant=tenant,
        brand_id=brand_id,
        brand_slug=payload.brand_id,
        report_config_id=payload.report_config_id,
        role=payload.role,
        timeframe=payload.timeframe,
        workflow_job_id=job_id,
    )
    started = await starter.start_report_generation(workflow_id=workflow_id, request=request)
    memory.update_workflow_job_handle(
        workflow_id=started.workflow_id,
        run_id=started.run_id,
        task_queue=started.task_queue,
    )
    job = memory.get_workflow_job(started.workflow_id)
    assert job is not None
    return schemas.WorkflowJob(
        id=job_id,
        workflow_id=job.workflow_id,
        run_id=job.run_id,
        workflow_type=job.workflow_type,
        status=job.status,
        task_queue=job.task_queue,
        created_at=(job.created_at or datetime.now(tz=UTC)).isoformat(),
    )


def _brand_id_for_slug(memory: SqlMemory, tenant: TenantContext, brand_slug: str) -> int:
    for brand in memory.list_brands_for_tenant(tenant):
        if brand.slug == brand_slug:
            return brand.id
    raise HTTPException(status_code=404, detail="Brand not found")
