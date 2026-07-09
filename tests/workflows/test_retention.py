from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from resound.memory import SignalRow, SqlMemory
from resound.models import RawSignal
from resound.workflows.retention import (
    RetentionRequest,
    RetentionWorkflow,
    apply_public_signal_retention,
)


def test_retention_deletes_old_uncited_signals_and_preserves_report_evidence(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'retention.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    old = datetime.now(tz=UTC) - timedelta(days=400)
    uncited_id = memory.record_signal(
        "acme",
        RawSignal(source="reddit", external_id="old-1", content="Uncited", posted_at=old),
        organization_id=org,
        brand_id=brand.id,
    )
    cited_id = memory.record_signal(
        "acme",
        RawSignal(source="reddit", external_id="old-2", content="Cited evidence", posted_at=old),
        organization_id=org,
        brand_id=brand.id,
    )
    run_id = memory.create_report_run(
        organization_id=org,
        brand_id=brand.id,
        team_id=None,
        role="founder",
        timeframe="7d",
        status="held_for_review",
    )
    memory.save_report_citation(
        report_run_id=run_id,
        signal_id=cited_id,
        section_title="Executive Summary",
        quote="Cited evidence",
        source="reddit",
        full_text="Cited evidence",
    )

    result = apply_public_signal_retention(memory, now=datetime.now(tz=UTC), retention_days=365)

    with memory.session() as session:
        remaining_ids = {row.id for row in session.execute(select(SignalRow)).scalars()}

    assert result.deleted_count == 1
    assert uncited_id not in remaining_ids
    assert cited_id in remaining_ids
    assert memory.list_report_citations(run_id)[0].full_text == "Cited evidence"


def test_retention_workflow_is_temporal_wrapped():
    request = RetentionRequest(retention_days=365)

    assert request.retention_days == 365
    assert hasattr(RetentionWorkflow, "run")
