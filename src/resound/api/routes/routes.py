from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query

from resound.api import projections, schemas
from resound.api.dependencies import get_memory, get_tenant_context
from resound.config import load_brand_config
from resound.memory import SqlMemory
from resound.tenancy import TenantContext

router = APIRouter(tags=["routes", "feedback"])


@router.get("/routes", operation_id="listRoutes", response_model=list[schemas.RouteAudit])
def list_routes(
    brand_id: str | None = Query(default=None, alias="brandId"),
    period: schemas.Period = "7d",
    limit: int = 50,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> list[schemas.RouteAudit]:
    return projections.list_routes(
        memory,
        tenant=tenant,
        brand_slug=brand_id,
        period=period,
        limit=limit,
    )


@router.patch(
    "/routes/{routeId}/reroute",
    operation_id="rerouteSignal",
    response_model=schemas.RouteAudit,
)
def reroute_signal(
    route_id: Annotated[int, Path(alias="routeId")],
    body: schemas.RerouteInput,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.RouteAudit:
    existing = projections._joined_row_for_route(memory, route_id, tenant=tenant)  # noqa: SLF001
    if existing is None:
        raise HTTPException(status_code=404, detail="Route not found")
    brand = _optional_brand_config(existing.signal.brand_slug)
    if brand is not None and body.owner not in projections.valid_owner_ids(brand):
        raise HTTPException(status_code=422, detail="Owner is not valid for this brand")

    audit = projections.reroute(
        memory,
        tenant=tenant,
        route_id=route_id,
        owner=body.owner,
        note=body.note,
        submitted_by=body.submitted_by,
        idempotency_key=idempotency_key,
    )
    if audit is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return audit


@router.post(
    "/routes/{routeId}/feedback",
    operation_id="submitFeedback",
    response_model=schemas.FeedbackEvent,
    status_code=201,
)
def submit_feedback(
    route_id: Annotated[int, Path(alias="routeId")],
    body: schemas.FeedbackInput,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.FeedbackEvent:
    feedback = projections.submit_feedback(
        memory,
        tenant=tenant,
        route_id=route_id,
        correct=body.correct,
        note=body.note,
        actioned=body.actioned,
        submitted_by=body.submitted_by,
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Route not found")
    return feedback


def _optional_brand_config(brand_slug: str):
    try:
        return load_brand_config(brand_slug)
    except FileNotFoundError:
        return None
