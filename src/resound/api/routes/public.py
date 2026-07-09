from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from resound.api import schemas
from resound.api.dependencies import get_memory, get_tenant_context
from resound.memory import SqlMemory
from resound.tenancy import TenantContext

router = APIRouter(tags=["public"])


@router.get(
    "/public/feed",
    operation_id="getPublicBrandFeed",
    response_model=schemas.PublicFeed,
)
def public_brand_feed(
    brand_id: str = Query(alias="brandId"),
    limit: int = Query(default=20, ge=1, le=50),
    memory: SqlMemory = Depends(get_memory),
) -> schemas.PublicFeed:
    rows = memory.list_public_feed_items(brand_id, limit)
    return schemas.PublicFeed(
        items=[
            schemas.PublicFeedItem(
                id=row.id,
                brand_id=row.brand_slug,
                source=row.source,
                content=row.content[:500],
                posted_at=row.posted_at.isoformat(),
                source_url=row.url,
            )
            for row in rows
        ],
        capped=True,
        export_available=False,
    )


@router.patch(
    "/public/feed/items/{signalId}/moderation",
    operation_id="moderatePublicFeedItem",
    response_model=schemas.PublicFeedModerationEvent,
)
def moderate_public_feed_item(
    signal_id: Annotated[int, Path(alias="signalId")],
    payload: schemas.PublicFeedModerationInput,
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> schemas.PublicFeedModerationEvent:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        event = memory.moderate_public_feed_item(
            signal_id=signal_id,
            organization_id=tenant.organization_id,
            action=payload.action,
            reason=payload.reason,
            actor=payload.actor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if event is None:
        raise HTTPException(status_code=404, detail="Public feed item not found")
    return schemas.PublicFeedModerationEvent(
        id=event.id,
        signal_id=event.signal_id,
        action=event.action,
        reason=event.reason,
        actor=event.actor,
        created_at=event.created_at.isoformat(),
    )
