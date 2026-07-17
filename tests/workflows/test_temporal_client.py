from __future__ import annotations

import asyncio
from dataclasses import dataclass

from temporalio.service import RPCError, RPCStatusCode

from resound.memory import SqlMemory, WorkflowJobRow, WorkflowLeaseRow
from resound.workflows import WorkflowRuntimeConfig
from resound.workflows import client as workflow_client
from resound.workflows.client import TemporalWorkflowStarter


def _starter() -> TemporalWorkflowStarter:
    return TemporalWorkflowStarter(
        WorkflowRuntimeConfig(
            address="temporal.test:7233",
            namespace="default",
            task_queue="task-4",
            worker_identity="test-worker",
        )
    )


@dataclass
class ResolvedIdentity:
    organization_id: int = 2
    brand_id: int = 3
    workflow_job_id: int = 5
    owner_token: str = "owner"


class _Execution:
    run_id = "described-run"


class _Info:
    execution = _Execution()


class _RawDescription:
    workflow_execution_info = _Info()


class _Description:
    raw_description = _RawDescription()


def test_ambiguous_start_describes_the_same_deterministic_id():
    requested_ids: list[str] = []

    class Handle:
        async def describe(self, **_kwargs):
            return _Description()

    class Client:
        def get_workflow_handle(self, workflow_id):
            requested_ids.append(workflow_id)
            return Handle()

    result = asyncio.run(
        _starter()._reconcile_public_listening_start(
            client=Client(),
            workflow_id="public-listening-sync:org:2:brand:3:job:5",
            request=ResolvedIdentity(),
            workflow="workflow",
            initial_error=TimeoutError("response lost"),
        )
    )

    assert requested_ids == ["public-listening-sync:org:2:brand:3:job:5"]
    assert result.run_id == "described-run"


def test_confirmed_absence_retries_start_with_the_same_id():
    calls: list[str] = []

    class Handle:
        async def describe(self, **_kwargs):
            raise RPCError("absent", RPCStatusCode.NOT_FOUND, b"")

    class Started:
        id = "public-listening-sync:org:2:brand:3:job:5"
        result_run_id = "new-run"

    class Client:
        def get_workflow_handle(self, workflow_id):
            calls.append(f"describe:{workflow_id}")
            return Handle()

        async def start_workflow(self, _workflow, _request, *, id, **_kwargs):
            calls.append(f"start:{id}")
            return Started()

    result = asyncio.run(
        _starter()._reconcile_public_listening_start(
            client=Client(),
            workflow_id="public-listening-sync:org:2:brand:3:job:5",
            request=ResolvedIdentity(),
            workflow="workflow",
            initial_error=TimeoutError("response lost"),
        )
    )

    assert result.run_id == "new-run"
    assert calls == [
        "describe:public-listening-sync:org:2:brand:3:job:5",
        "start:public-listening-sync:org:2:brand:3:job:5",
    ]


def test_start_error_classification_distinguishes_absence_and_ambiguity():
    absent = RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
    timeout = RPCError("deadline", RPCStatusCode.DEADLINE_EXCEEDED, b"")
    invalid = RPCError("invalid", RPCStatusCode.INVALID_ARGUMENT, b"")

    assert workflow_client._workflow_confirmed_absent(absent)
    assert not workflow_client._workflow_confirmed_absent(timeout)
    assert workflow_client._definitive_start_rejection(invalid)
    assert not workflow_client._definitive_start_rejection(timeout)


def test_resolved_workflow_id_is_job_scoped():
    assert workflow_client._resolved_public_listening_workflow_id(ResolvedIdentity()) == (
        "public-listening-sync:org:2:brand:3:job:5"
    )


def test_start_unknown_preserves_owner_lease_and_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{tmp_path / 'start-unknown.db'}")
    memory = SqlMemory()
    organization_id = memory.ensure_organization("org")
    brand = memory.ensure_brand(organization_id, "brand")
    workflow_id = f"public-listening-sync:org:{organization_id}:brand:{brand.id}:job:placeholder"
    job_id = memory.create_workflow_job(
        workflow_id=workflow_id,
        workflow_type="PublicListeningSyncWorkflow",
        organization_id=organization_id,
        brand_id=brand.id,
    )
    memory.acquire_workflow_lease(
        organization_id=organization_id,
        brand_id=brand.id,
        workflow_job_id=job_id,
        owner_token="owner",
    )
    request = ResolvedIdentity(
        organization_id=organization_id,
        brand_id=brand.id,
        workflow_job_id=job_id,
        owner_token="owner",
    )

    workflow_client._preserve_start_unknown(request, ["TimeoutError"])

    with memory.session() as session:
        job = session.get(WorkflowJobRow, job_id)
        lease = session.query(WorkflowLeaseRow).one()
        assert job.status == "start_unknown"
        assert job.start_reconciliation_diagnostics["attempt_error_classes"] == ["TimeoutError"]
        assert lease.status == "active"
        assert lease.owner_token == "owner"
