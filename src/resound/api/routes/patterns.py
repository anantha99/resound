from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from resound.api import projections, schemas
from resound.api.dependencies import get_memory, get_tenant_context
from resound.memory import SqlMemory
from resound.tenancy import TenantContext

router = APIRouter(tags=["patterns"])


@router.get("/patterns", operation_id="listPatterns", response_model=list[schemas.Pattern])
def list_patterns(
    brand_id: str | None = Query(default=None, alias="brandId"),
    area: str | None = None,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> list[schemas.Pattern]:
    return projections.list_patterns(memory, brand_id, area, tenant=tenant)


@router.get(
    "/patterns/{patternId}",
    operation_id="getPattern",
    response_model=schemas.PatternDetail,
)
def get_pattern(
    pattern_id: Annotated[int, Path(alias="patternId")],
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.PatternDetail:
    pattern = projections.get_pattern(memory, pattern_id, tenant=tenant)
    if pattern is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return pattern
