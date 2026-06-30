from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from resound.api import projections, schemas
from resound.api.dependencies import get_memory
from resound.memory import SqlMemory

router = APIRouter(tags=["signals"])


@router.get("/signals", operation_id="listSignals", response_model=schemas.SignalList)
def list_signals(
    brand_id: str | None = Query(default=None, alias="brandId"),
    source: str | None = None,
    area: str | None = None,
    severity: str | None = None,
    sentiment: str | None = None,
    period: schemas.Period = "7d",
    limit: int = 50,
    offset: int = 0,
    memory: SqlMemory = Depends(get_memory),
) -> schemas.SignalList:
    return projections.list_signals(
        memory,
        brand_slug=brand_id,
        source=source,
        area=area,
        severity=severity,
        sentiment=sentiment,
        period=period,
        limit=limit,
        offset=offset,
    )


@router.get("/signals/critical", operation_id="getCriticalSignals")
def get_critical_signals(
    brand_id: str | None = Query(default=None, alias="brandId"),
    period: schemas.Period = "7d",
    memory: SqlMemory = Depends(get_memory),
) -> list[schemas.SignalDetail]:
    return projections.critical_signals(memory, brand_id, period)


@router.get("/signals/{signalId}", operation_id="getSignal", response_model=schemas.SignalDetail)
def get_signal(
    signal_id: Annotated[int, Path(alias="signalId")],
    memory: SqlMemory = Depends(get_memory),
) -> schemas.SignalDetail:
    signal = projections.get_signal(memory, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal
