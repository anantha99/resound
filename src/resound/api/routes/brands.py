from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from resound.api import projections, schemas
from resound.api.dependencies import get_memory
from resound.memory import SqlMemory

router = APIRouter(tags=["brands"])


@router.get("/brands", operation_id="listBrands", response_model=list[schemas.Brand])
def list_brands(memory: SqlMemory = Depends(get_memory)) -> list[schemas.Brand]:
    return projections.list_brands(memory)


@router.get(
    "/brands/{brandId}/stats/{period}",
    operation_id="getBrandStats",
    response_model=schemas.BrandStats,
)
def get_brand_stats(
    brand_id: Annotated[str, Path(alias="brandId")],
    period: schemas.Period,
    memory: SqlMemory = Depends(get_memory),
) -> schemas.BrandStats:
    if projections.get_brand(brand_id, memory) is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return projections.brand_stats(memory, brand_id, period)
