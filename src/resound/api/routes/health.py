from __future__ import annotations

from fastapi import APIRouter, Depends

from resound.api import projections, schemas
from resound.api.dependencies import get_memory
from resound.config import env
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


@router.get("/readiness", operation_id="readinessCheck", response_model=schemas.ReadinessStatus)
def readiness_check(memory: SqlMemory = Depends(get_memory)) -> schemas.ReadinessStatus:
    checks = [
        schemas.ReadinessCheck(
            name="database",
            status="ok" if memory.engine else "error",
            detail="SQLAlchemy engine initialized" if memory.engine else "No database engine",
        ),
        schemas.ReadinessCheck(
            name="temporal",
            status="ok" if env("RESOUND_TEMPORAL_ADDRESS") else "warning",
            detail=env("RESOUND_TEMPORAL_ADDRESS", "Using default Temporal address"),
        ),
        schemas.ReadinessCheck(
            name="openrouter",
            status="ok" if env("OPENROUTER_API_KEY") else "warning",
            detail="Configured" if env("OPENROUTER_API_KEY") else "OPENROUTER_API_KEY is not set",
        ),
        schemas.ReadinessCheck(
            name="apify",
            status="ok" if env("APIFY_API_TOKEN") or env("APIFY_TOKEN") else "warning",
            detail=(
                "Configured"
                if env("APIFY_API_TOKEN") or env("APIFY_TOKEN")
                else "APIFY token is not set"
            ),
        ),
    ]
    status = "ok" if all(check.status == "ok" for check in checks) else "degraded"
    return schemas.ReadinessStatus(status=status, checks=checks)
