from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from resound.api import projections, schemas
from resound.api.dependencies import get_memory, get_tenant_context, get_workflow_starter
from resound.config import load_brand_config
from resound.memory import BrandRow, SqlMemory
from resound.tenancy import TenantContext
from resound.workflows.client import WorkflowStarter
from resound.workflows.public_listening import PublicListeningSyncRequest

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
    workflow_id = f"public-listening-sync-{payload.brand_id}-{uuid4().hex[:12]}"
    cfg = _brand_config(payload.brand_id)
    job_id = memory.create_workflow_job(
        workflow_id=workflow_id,
        workflow_type="PublicListeningSyncWorkflow",
        organization_id=tenant.organization_id,
        brand_id=brand.id,
    )
    request = PublicListeningSyncRequest(
        tenant=tenant,
        brand_id=brand.id,
        brand_slug=brand.slug,
        brand_context=cfg.get("brand_context", ""),
        routing_config=cfg.get("routing", {}),
        people_config=cfg.get("people", {}),
        workflow_job_id=job_id,
    )
    started = await starter.start_public_listening_sync(
        workflow_id=workflow_id,
        request=request,
    )
    memory.update_workflow_job_handle(
        workflow_id=started.workflow_id,
        run_id=started.run_id,
        task_queue=started.task_queue,
    )
    job = memory.get_workflow_job(started.workflow_id)
    assert job is not None
    return _workflow_job_schema(job_id, job)


def _tenant_brand(memory: SqlMemory, tenant: TenantContext, brand_slug: str) -> BrandRow:
    if projections.get_brand(brand_slug, memory, tenant) is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    for row in memory.list_brands_for_tenant(tenant):
        if row.slug == brand_slug:
            return row
    raise HTTPException(status_code=404, detail="Brand not found")


def _brand_config(brand_slug: str) -> dict:
    try:
        cfg = load_brand_config(brand_slug)
    except FileNotFoundError:
        return {"brand_context": "", "routing": {}, "people": {}}
    return {
        "brand_context": cfg.understanding,
        "routing": cfg.routing,
        "people": cfg.people,
    }


def _workflow_job_schema(job_id: int, row) -> schemas.WorkflowJob:
    return schemas.WorkflowJob(
        id=job_id,
        workflow_id=row.workflow_id,
        run_id=row.run_id,
        workflow_type=row.workflow_type,
        status=row.status,
        task_queue=row.task_queue,
        created_at=(row.created_at or datetime.now(tz=UTC)).isoformat(),
    )
