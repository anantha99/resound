from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from resound.api import schemas
from resound.api.dependencies import get_memory, get_tenant_context, get_workflow_starter
from resound.memory import SqlMemory
from resound.tenancy import TenantContext
from resound.workflows.client import WorkflowStarter
from resound.workflows.listening_setup import ListeningProfileSetupRequest

router = APIRouter(tags=["listening-profiles"])


@router.post(
    "/listening-profiles/setup",
    operation_id="startListeningProfileSetup",
    response_model=schemas.WorkflowJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_listening_profile_setup(
    payload: schemas.ListeningProfileSetupInput,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
    starter: WorkflowStarter = Depends(get_workflow_starter),
) -> schemas.WorkflowJob:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    brand_id = _brand_id_for_slug(memory, tenant, payload.brand_id)
    workflow_id = f"listening-profile-setup-{payload.brand_id}-{uuid4().hex[:12]}"
    job_id = memory.create_workflow_job(
        workflow_id=workflow_id,
        workflow_type="ListeningProfileSetupWorkflow",
        organization_id=tenant.organization_id,
        brand_id=brand_id,
    )
    request = ListeningProfileSetupRequest(
        tenant=tenant,
        brand_id=brand_id,
        brand_slug=payload.brand_id,
        brand_names=payload.brand_names,
        product_names=payload.product_names,
        competitor_names=payload.competitor_names,
        excluded_terms=payload.excluded_terms,
        locale=payload.locale,
        language=payload.language,
        setup_notes=payload.setup_notes,
        workflow_job_id=job_id,
    )
    started = await starter.start_listening_profile_setup(workflow_id=workflow_id, request=request)
    memory.update_workflow_job_handle(
        workflow_id=started.workflow_id,
        run_id=started.run_id,
        task_queue=started.task_queue,
    )
    job = memory.get_workflow_job(started.workflow_id)
    assert job is not None
    return _workflow_job_schema(job_id, job)


@router.patch(
    "/listening-profiles/suggestions/{suggestion_id}",
    operation_id="decideListeningProfileSuggestion",
    response_model=schemas.ListeningProfileSuggestion,
)
def decide_listening_profile_suggestion(
    suggestion_id: int,
    payload: schemas.ListeningProfileSuggestionDecision,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.ListeningProfileSuggestion:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        row = memory.apply_listening_profile_suggestion_decision(
            suggestion_id=suggestion_id,
            organization_id=tenant.organization_id,
            decision=payload.decision,
            edited_value=payload.edited_value,
            authored_by="user",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Listening profile suggestion not found")
    return _suggestion_schema(row)


def _brand_id_for_slug(memory: SqlMemory, tenant: TenantContext, brand_slug: str) -> int:
    for brand in memory.list_brands_for_tenant(tenant):
        if brand.slug == brand_slug:
            return brand.id
    raise HTTPException(status_code=404, detail="Brand not found")


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


def _suggestion_schema(row) -> schemas.ListeningProfileSuggestion:
    return schemas.ListeningProfileSuggestion(
        id=row.id,
        profile_id=row.profile_id,
        suggestion_type=row.suggestion_type,
        value=row.value,
        reason=row.reason,
        status=row.status,
        created_at=(row.created_at or datetime.now(tz=UTC)).isoformat(),
        resolved_at=row.resolved_at.isoformat() if row.resolved_at else None,
    )
