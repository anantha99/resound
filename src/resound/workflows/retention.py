"""Retention workflow helpers for public listening data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select

from resound.memory import ReportCitationRow, SignalRow, SqlMemory
from resound.workflows.temporal_compat import activity, workflow


@dataclass(frozen=True)
class RetentionResult:
    deleted_count: int
    preserved_cited_count: int


@dataclass(frozen=True)
class RetentionRequest:
    retention_days: int = 365


def apply_public_signal_retention(
    memory: SqlMemory,
    *,
    now: datetime,
    retention_days: int = 365,
) -> RetentionResult:
    cutoff = now - timedelta(days=retention_days)
    if cutoff.tzinfo is not None:
        cutoff = cutoff.replace(tzinfo=None)

    with memory.session() as session:
        cited_ids = {
            signal_id
            for signal_id in session.execute(select(ReportCitationRow.signal_id)).scalars()
            if signal_id is not None
        }
        old_public_signals = list(
            session.execute(
                select(SignalRow).where(
                    SignalRow.source_mode == "public_listening",
                    SignalRow.posted_at < cutoff,
                ),
            ).scalars()
        )
        deleted_count = 0
        preserved_cited_count = 0
        for row in old_public_signals:
            if row.id in cited_ids:
                preserved_cited_count += 1
                continue
            session.delete(row)
            deleted_count += 1
        session.commit()

    return RetentionResult(
        deleted_count=deleted_count,
        preserved_cited_count=preserved_cited_count,
    )


@activity.defn
async def retention_activity(request: RetentionRequest) -> RetentionResult:
    return apply_public_signal_retention(
        SqlMemory(),
        now=datetime.utcnow(),
        retention_days=request.retention_days,
    )


@workflow.defn
class RetentionWorkflow:
    @workflow.run
    async def run(self, request: RetentionRequest) -> RetentionResult:
        return await workflow.execute_activity(
            retention_activity,
            request,
            start_to_close_timeout=timedelta(minutes=10),
        )
