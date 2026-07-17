from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, status

from resound.api import projections, schemas
from resound.api.dependencies import get_memory, get_tenant_context, get_workflow_starter
from resound.config import load_brand_config
from resound.memory import BrandRow, SqlMemory
from resound.social.contracts import SourceSyncInput as ResolvedSourceSyncInput
from resound.tenancy import TenantContext
from resound.workflows.client import WorkflowStarter, WorkflowStartUnknownError
from resound.workflows.start_service import (
    PublicListeningStartConflictError,
    start_public_listening_workflow,
)

router = APIRouter(tags=["workflows"])


@router.post(
    "/workflows/source-sync",
    operation_id="startSourceSync",
    response_model=schemas.WorkflowJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_source_sync(
    payload: schemas.SourceSyncInput,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
    starter: WorkflowStarter = Depends(get_workflow_starter),
) -> schemas.WorkflowJob:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    brand = _tenant_brand(memory, tenant, payload.brand_id)
    try:
        request_input = ResolvedSourceSyncInput.model_validate(
            {
                **payload.model_dump(mode="json", exclude_none=True),
                "internal_brand_id": brand.id,
            }
        )
        job = await start_public_listening_workflow(
            request_input=request_input,
            brand_config=load_brand_config(payload.brand_id),
            memory=memory,
            organization_id=tenant.organization_id,
            brand_id=brand.id,
            starter=starter,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PublicListeningStartConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WorkflowStartUnknownError:
        raise HTTPException(status_code=503, detail="Workflow start acceptance is unresolved")
    return _workflow_job_schema(job)


@router.get(
    "/workflows/{workflowId}",
    operation_id="getWorkflow",
    response_model=schemas.WorkflowJob,
)
def get_workflow(
    workflow_id: str = Path(alias="workflowId"),
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.WorkflowJob:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    row = memory.get_workflow_job(workflow_id)
    if row is None or row.organization_id != tenant.organization_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _workflow_job_schema(row)


def _tenant_brand(memory: SqlMemory, tenant: TenantContext, brand_slug: str) -> BrandRow:
    if projections.get_brand(brand_slug, memory, tenant) is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    for row in memory.list_brands_for_tenant(tenant):
        if row.slug == brand_slug:
            return row
    raise HTTPException(status_code=404, detail="Brand not found")


def _workflow_job_schema(row) -> schemas.WorkflowJob:
    return schemas.WorkflowJob(
        id=row.id,
        workflow_id=row.workflow_id,
        run_id=row.run_id,
        workflow_type=row.workflow_type,
        status=row.status,
        task_queue=row.task_queue,
        result_schema_version=row.result_schema_version,
        result_summary=row.result_summary,
        request_fingerprint_summary=row.request_fingerprint_summary,
        start_reconciliation_diagnostics=row.start_reconciliation_diagnostics,
        created_at=(row.created_at or datetime.now(tz=UTC)).isoformat(),
    )
