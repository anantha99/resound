from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from resound.api import schemas
from resound.api.dependencies import get_memory, get_tenant_context
from resound.memory import SqlMemory
from resound.tenancy import TenantContext

router = APIRouter(tags=["operations"])


@router.get("/source-health", operation_id="listSourceHealth")
def list_source_health(
    brand_id: str = Query(alias="brandId"),
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> list[schemas.SourceHealth]:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    brand = _brand_for_slug(memory, tenant, brand_id)
    return [
        schemas.SourceHealth(
            source_type=row.source_type,
            canonical_source=row.canonical_source,
            path=row.path,
            provider=row.provider,
            status=row.status,
            last_success_at=row.last_success_at.isoformat() if row.last_success_at else None,
            last_failure_at=row.last_failure_at.isoformat() if row.last_failure_at else None,
            last_run_id=row.last_run_id,
            item_count=row.item_count,
            fetched_count=row.fetched_count,
            processed_count=row.processed_count,
            duplicate_count=row.duplicate_count,
            cost_usd=row.cost_usd,
            provenance=row.provenance or {},
            issues=[_safe_issue(issue) for issue in (row.issues or [])],
            error_message=row.error_message,
        )
        for row in memory.list_source_health(tenant.organization_id, brand.id)
    ]


def _safe_issue(issue: dict) -> dict:
    return {
        key: issue[key]
        for key in ("path", "code", "issue_class", "message", "retryable", "preserved_work")
        if key in issue
    }


@router.get("/telemetry/llm", operation_id="getLlmTelemetry", response_model=schemas.LLMTelemetry)
def get_llm_telemetry(
    brand_id: str = Query(alias="brandId"),
    period: schemas.Period = "7d",
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.LLMTelemetry:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    _brand_for_slug(memory, tenant, brand_id)
    since = _period_since(period)
    return schemas.LLMTelemetry(
        brand_id=brand_id,
        period=period,
        costs=memory.query_llm_costs(brand_id, since, organization_id=tenant.organization_id),
        latency=memory.query_llm_latency(brand_id, since, organization_id=tenant.organization_id),
        fallback_rate=memory.query_fallback_rate(
            brand_id,
            since,
            organization_id=tenant.organization_id,
        ),
    )


@router.get(
    "/evaluations/summary",
    operation_id="getEvaluationSummary",
    response_model=schemas.EvaluationSummary,
)
def get_evaluation_summary(
    brand_id: str = Query(alias="brandId"),
    period: schemas.Period = "7d",
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.EvaluationSummary:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    brand = _brand_for_slug(memory, tenant, brand_id)
    since = _period_since(period)
    costs = memory.query_llm_costs(brand_id, since, organization_id=tenant.organization_id)
    health = memory.list_source_health(tenant.organization_id, brand.id)
    return schemas.EvaluationSummary(
        brand_id=brand_id,
        report_runs_by_status=memory.count_report_runs_by_status(
            organization_id=tenant.organization_id,
            brand_id=brand.id,
        ),
        source_failure_count=len([row for row in health if row.status != "ok"]),
        total_llm_cost_usd=sum(row["total_cost_usd"] for row in costs),
    )


def _brand_for_slug(memory: SqlMemory, tenant: TenantContext, brand_slug: str):
    for brand in memory.list_brands_for_tenant(tenant):
        if brand.slug == brand_slug:
            return brand
    raise HTTPException(status_code=404, detail="Brand not found")


def _period_since(period: schemas.Period) -> datetime:
    now = datetime.utcnow()
    if period == "24h":
        return now - timedelta(days=1)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    start_month = ((now.month - 1) // 3) * 3 + 1
    return datetime(now.year, start_month, 1)
