from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from resound.memory import SignalRow, SqlMemory, WorkflowLeaseRow
from resound.models import RawSignal
from resound.workflows.leases import public_listening_workflow_id
from resound.workflows.result_persistence import bounded_result_summary


def _memory(tmp_path) -> tuple[SqlMemory, int, int]:
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'runtime.db'}")
    organization_id = memory.ensure_organization("org", "Org")
    brand = memory.ensure_brand(organization_id, "acme", "Acme")
    return memory, organization_id, brand.id


def test_native_identity_is_unique_across_x_aliases_on_sqlite(tmp_path):
    memory, organization_id, brand_id = _memory(tmp_path)
    timestamp = datetime.now(UTC)

    ids = [
        memory.record_signal(
            "acme",
            RawSignal(
                source=source,
                external_id=f"legacy-{source}",
                content="Same tweet",
                posted_at=timestamp,
                raw_metadata={
                    "canonical_platform": platform,
                    "content_kind": "post",
                    "provider_native_id": "tweet-123",
                },
            ),
            organization_id=organization_id,
            brand_id=brand_id,
        )
        for source, platform in (("twitter", "twitter"), ("x", "x"))
    ]

    with memory.session() as session:
        count = session.scalar(select(func.count()).select_from(SignalRow))
    assert ids[0] == ids[1]
    assert count == 1


def test_canonical_identity_contract_rejects_partial_rows(tmp_path):
    memory, organization_id, brand_id = _memory(tmp_path)
    with pytest.raises(ValueError, match="exactly one identity"):
        memory.record_signal(
            "acme",
            RawSignal(
                source="x",
                external_id="ambiguous",
                content="Missing native/fallback identity",
                posted_at=datetime.now(UTC),
                raw_metadata={"canonical_platform": "x", "content_kind": "post"},
            ),
            organization_id=organization_id,
            brand_id=brand_id,
        )


def test_workflow_lease_takeover_and_owner_checked_finalization(tmp_path):
    memory, organization_id, brand_id = _memory(tmp_path)
    first_job = memory.create_workflow_job(
        workflow_id="job:first",
        workflow_type="public_listening_sync",
        organization_id=organization_id,
        brand_id=brand_id,
    )
    second_job = memory.create_workflow_job(
        workflow_id="job:second",
        workflow_type="public_listening_sync",
        organization_id=organization_id,
        brand_id=brand_id,
    )
    started = datetime(2026, 7, 17, 12, 0, 0)
    first = memory.acquire_workflow_lease(
        organization_id=organization_id,
        brand_id=brand_id,
        workflow_job_id=first_job,
        owner_token="first-owner",
        now=started,
    )
    assert first is not None
    assert (
        memory.acquire_workflow_lease(
            organization_id=organization_id,
            brand_id=brand_id,
            workflow_job_id=second_job,
            owner_token="blocked-owner",
            now=started + timedelta(seconds=119),
        )
        is None
    )

    second = memory.acquire_workflow_lease(
        organization_id=organization_id,
        brand_id=brand_id,
        workflow_job_id=second_job,
        owner_token="second-owner",
        now=started + timedelta(seconds=120),
    )
    assert second is not None
    assert not memory.finalize_workflow_job(
        workflow_job_id=first_job,
        organization_id=organization_id,
        brand_id=brand_id,
        owner_token="first-owner",
        status="failed",
        result_summary={"status": "failed", "sources": []},
        now=started + timedelta(seconds=121),
    )
    assert memory.finalize_workflow_job(
        workflow_job_id=second_job,
        organization_id=organization_id,
        brand_id=brand_id,
        owner_token="second-owner",
        status="completed",
        result_summary={"status": "completed", "sources": []},
        now=started + timedelta(seconds=121),
    )
    with memory.session() as session:
        lease = session.execute(select(WorkflowLeaseRow)).scalar_one()
    assert lease.status == "completed"


def test_result_projection_has_independent_collection_bounds():
    result = bounded_result_summary(
        {
            "status": "partial",
            "sources": [
                {
                    "source": "x",
                    "max_signals_per_source": 7,
                    "processed_count": 7,
                    "cap_reached": True,
                    "paths": [
                        {
                            "path": "mention_discovery",
                            "runs": [{"run_id": str(index)} for index in range(12)],
                            "datasets": [{"dataset_id": str(index)} for index in range(30)],
                            "issues": [{"message": "x" * 1500} for _ in range(22)],
                            "associations": [{"signal_id": index} for index in range(105)],
                        }
                    ],
                }
            ],
        }
    )
    path = result["sources"][0]["paths"][0]
    assert result["schema_version"] == 1
    assert result["sources"][0]["max_signals_per_source"] == 7
    assert len(path["runs"]) == 10 and path["runs_truncated_count"] == 2
    assert len(path["datasets"]) == 25 and path["datasets_truncated_count"] == 5
    assert len(path["issues"]) == 20 and path["issues_truncated_count"] == 2
    assert len(path["associations"]) == 100 and path["associations_truncated_count"] == 5
    assert len(path["issues"][0]["message"]) == 1000


def test_public_listening_workflow_id_is_job_scoped_and_deterministic():
    assert public_listening_workflow_id(3, 5, 8) == (
        "public-listening-sync:org:3:brand:5:job:8"
    )
