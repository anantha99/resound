"""Shared public-listening workflow start orchestration for API and CLI callers."""

from __future__ import annotations

import secrets
from uuid import uuid4

from sqlalchemy import func, select

from resound.config import BrandConfig
from resound.memory import SqlMemory, WorkflowJobRow, WorkflowLeaseRow
from resound.social.contracts import ResolvedPublicListeningRequest, SourceSyncInput
from resound.social.resolver import resolve_public_listening_request
from resound.workflows.client import WorkflowStarter
from resound.workflows.leases import PUBLIC_LISTENING_WORKFLOW_KIND, public_listening_workflow_id


class PublicListeningStartConflictError(RuntimeError):
    """Another workflow owns the brand-scoped public-listening lease."""


async def start_public_listening_workflow(
    *,
    request_input: SourceSyncInput,
    brand_config: BrandConfig,
    memory: SqlMemory,
    organization_id: int,
    brand_id: int,
    starter: WorkflowStarter,
) -> WorkflowJobRow:
    """Resolve and start a sync, or reconcile its preserved ambiguous start."""

    preserved = _preserved_start_unknown(
        memory,
        organization_id=organization_id,
        brand_id=brand_id,
    )
    if preserved is not None:
        job, snapshot = preserved
        started = await starter.start_public_listening_sync(
            workflow_id=job.workflow_id,
            request=snapshot,
        )
        memory.update_workflow_job_handle(
            workflow_id=started.workflow_id,
            run_id=started.run_id,
            task_queue=started.task_queue,
        )
        reconciled = memory.get_workflow_job(job.workflow_id)
        assert reconciled is not None
        return reconciled

    placeholder_id = f"resolving-public-listening-{uuid4().hex}"
    job_id = memory.create_workflow_job(
        workflow_id=placeholder_id,
        workflow_type="PublicListeningSyncWorkflow",
        organization_id=organization_id,
        brand_id=brand_id,
        status="resolving",
    )
    workflow_id = public_listening_workflow_id(organization_id, brand_id, job_id)
    owner_token = secrets.token_urlsafe(32)
    try:
        resolved = resolve_public_listening_request(
            request_input,
            brand_config=brand_config,
            memory=memory,
            organization_id=organization_id,
            workflow_job_id=job_id,
            owner_token=owner_token,
        )
        fingerprint_summary = {
            source: fingerprint.model_dump(mode="json")
            for source, fingerprint in resolved.fingerprints.items()
        }
        memory.configure_workflow_job(
            workflow_job_id=job_id,
            workflow_id=workflow_id,
            resolved_config_snapshot=resolved.model_dump(mode="json"),
            request_fingerprint_summary=fingerprint_summary,
        )
    except Exception:
        memory.fail_workflow_start(workflow_job_id=job_id, owner_token=None)
        raise

    lease = memory.acquire_workflow_lease(
        organization_id=organization_id,
        brand_id=brand_id,
        workflow_job_id=job_id,
        owner_token=owner_token,
    )
    if lease is None:
        memory.fail_workflow_start(workflow_job_id=job_id, owner_token=None, status="conflict")
        raise PublicListeningStartConflictError("A public-listening sync is already active")

    try:
        started = await starter.start_public_listening_sync(
            workflow_id=workflow_id,
            request=resolved,
        )
    except Exception:
        current = memory.get_workflow_job(workflow_id)
        if current is None or current.status != "start_unknown":
            memory.fail_workflow_start(workflow_job_id=job_id, owner_token=owner_token)
        raise
    memory.update_workflow_job_handle(
        workflow_id=started.workflow_id,
        run_id=started.run_id,
        task_queue=started.task_queue,
    )
    job = memory.get_workflow_job(started.workflow_id)
    assert job is not None
    return job


def _preserved_start_unknown(
    memory: SqlMemory,
    *,
    organization_id: int,
    brand_id: int,
) -> tuple[WorkflowJobRow, ResolvedPublicListeningRequest] | None:
    with memory.session() as session:
        row = session.execute(
            select(WorkflowJobRow, WorkflowLeaseRow)
            .join(WorkflowLeaseRow, WorkflowLeaseRow.workflow_job_id == WorkflowJobRow.id)
            .where(
                WorkflowJobRow.organization_id == organization_id,
                WorkflowJobRow.brand_id == brand_id,
                WorkflowJobRow.status == "start_unknown",
                WorkflowLeaseRow.workflow_kind == PUBLIC_LISTENING_WORKFLOW_KIND,
                WorkflowLeaseRow.status == "active",
                WorkflowLeaseRow.expires_at > func.current_timestamp(),
            )
            .order_by(WorkflowJobRow.id.desc())
        ).first()
        if row is None:
            return None
        job, lease = row
        snapshot = job.resolved_config_snapshot
        if not snapshot:
            return None
        resolved = ResolvedPublicListeningRequest.model_validate(snapshot)
        expected_id = public_listening_workflow_id(organization_id, brand_id, job.id)
        if job.workflow_id != expected_id:
            raise ValueError("preserved workflow job has a non-deterministic workflow ID")
        if resolved.owner_token != lease.owner_token or resolved.workflow_job_id != job.id:
            raise ValueError("preserved workflow snapshot does not match its owning lease")
        session.expunge(job)
        return job, resolved
