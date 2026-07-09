"""Realtime event helpers for dashboard streams."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter(tags=["events"])


@router.get("/events", operation_id="streamEvents")
async def stream_events() -> StreamingResponse:
    async def empty_stream() -> AsyncIterator[str]:
        yield ": resound event stream ready\n\n"

    return StreamingResponse(empty_stream(), media_type="text/event-stream")
