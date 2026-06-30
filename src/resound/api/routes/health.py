from __future__ import annotations

from fastapi import APIRouter, Depends

from resound.api import projections, schemas
from resound.api.dependencies import get_memory
from resound.memory import SqlMemory

router = APIRouter(tags=["health"])


@router.get("/healthz", operation_id="healthCheck", response_model=schemas.HealthStatus)
def health_check(memory: SqlMemory = Depends(get_memory)) -> schemas.HealthStatus:
    return schemas.HealthStatus(
        status="ok",
        version="0.1.0",
        database="ok" if memory.engine else "unknown",
        brands_count=len(projections.list_brand_slugs()),
    )
