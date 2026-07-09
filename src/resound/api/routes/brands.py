from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from resound.api import projections, schemas
from resound.api.dependencies import get_memory, get_tenant_context
from resound.memory import SqlMemory
from resound.tenancy import TenantContext

router = APIRouter(tags=["brands"])


@router.get("/brands", operation_id="listBrands", response_model=list[schemas.Brand])
def list_brands(
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> list[schemas.Brand]:
    return projections.list_brands(memory, tenant)


@router.get(
    "/brands/{brandId}/stats/{period}",
    operation_id="getBrandStats",
    response_model=schemas.BrandStats,
)
def get_brand_stats(
    brand_id: Annotated[str, Path(alias="brandId")],
    period: schemas.Period,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.BrandStats:
    if projections.get_brand(brand_id, memory, tenant) is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return projections.brand_stats(memory, brand_id, period, tenant=tenant)
