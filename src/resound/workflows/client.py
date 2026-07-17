"""Temporal workflow start helpers used by API commands."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from temporalio.contrib.pydantic import pydantic_data_converter

from resound.config import env
from resound.reports.generation import ReportGenerationRequest, ReportGenerationWorkflow
from resound.workflows import WorkflowRuntimeConfig
from resound.workflows.leases import (
    PUBLIC_LISTENING_START_UNKNOWN_TTL_SECONDS,
    public_listening_workflow_id,
)
from resound.workflows.listening_setup import (
    ListeningProfileSetupRequest,
    ListeningProfileSetupWorkflow,
)

START_RECONCILIATION_SECONDS = 30.0
START_RECONCILIATION_INITIAL_DELAY_SECONDS = 0.25
START_RECONCILIATION_MAX_DELAY_SECONDS = 2.0


class WorkflowStartUnknownError(RuntimeError):
    """Temporal may have accepted the deterministic start; owning lease is preserved."""


@dataclass(frozen=True)
class WorkflowStartResult:
    workflow_id: str
    run_id: str | None
    task_queue: str


class WorkflowStarter(Protocol):
    async def start_report_generation(
        self,
        *,
        workflow_id: str,
        request: ReportGenerationRequest,
    ) -> WorkflowStartResult: ...

    async def start_public_listening_sync(
        self,
        *,
        workflow_id: str,
        request,
    ) -> WorkflowStartResult: ...

    async def start_listening_profile_setup(
        self,
        *,
        workflow_id: str,
        request: ListeningProfileSetupRequest,
    ) -> WorkflowStartResult: ...


class TemporalWorkflowStarter:
    def __init__(self, config: WorkflowRuntimeConfig | None = None):
        self.config = config or WorkflowRuntimeConfig.from_env()

    async def start_report_generation(
        self,
        *,
        workflow_id: str,
        request: ReportGenerationRequest,
    ) -> WorkflowStartResult:
        from temporalio.client import Client

        client = await Client.connect(
            self.config.address,
            namespace=self.config.namespace,
            data_converter=pydantic_data_converter,
        )
        handle = await client.start_workflow(
            ReportGenerationWorkflow.run,
            request,
            id=workflow_id,
            task_queue=self.config.task_queue,
        )
        return WorkflowStartResult(
            workflow_id=handle.id,
            run_id=handle.result_run_id,
            task_queue=self.config.task_queue,
        )

    async def start_public_listening_sync(
        self,
        *,
        workflow_id: str,
        request,
    ) -> WorkflowStartResult:
        from temporalio.client import Client
        from temporalio.common import WorkflowIDReusePolicy

        from resound.workflows.public_listening import PublicListeningSyncWorkflow

        expected_id = _resolved_public_listening_workflow_id(request)
        if expected_id is not None and workflow_id != expected_id:
            raise ValueError(f"public-listening workflow ID must be deterministic: {expected_id}")
        client = await Client.connect(
            self.config.address,
            namespace=self.config.namespace,
            data_converter=pydantic_data_converter,
        )
        try:
            handle = await client.start_workflow(
                PublicListeningSyncWorkflow.run,
                request,
                id=workflow_id,
                task_queue=self.config.task_queue,
                execution_timeout=timedelta(minutes=30),
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            return _start_result(handle, self.config.task_queue)
        except Exception as exc:
            if _definitive_start_rejection(exc):
                raise
            return await self._reconcile_public_listening_start(
                client=client,
                workflow_id=workflow_id,
                request=request,
                workflow=PublicListeningSyncWorkflow.run,
                initial_error=exc,
            )

    async def _reconcile_public_listening_start(
        self,
        *,
        client,
        workflow_id: str,
        request,
        workflow,
        initial_error: Exception,
    ) -> WorkflowStartResult:
        from temporalio.common import WorkflowIDReusePolicy
        from temporalio.exceptions import WorkflowAlreadyStartedError

        deadline = time.monotonic() + START_RECONCILIATION_SECONDS
        delay = START_RECONCILIATION_INITIAL_DELAY_SECONDS
        diagnostics = [type(initial_error).__name__]
        while time.monotonic() < deadline:
            handle = client.get_workflow_handle(workflow_id)
            try:
                description = await handle.describe(rpc_timeout=timedelta(seconds=2))
                return WorkflowStartResult(
                    workflow_id=workflow_id,
                    run_id=_description_run_id(description),
                    task_queue=self.config.task_queue,
                )
            except Exception as describe_error:
                diagnostics.append(type(describe_error).__name__)
                if not _workflow_confirmed_absent(describe_error):
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, START_RECONCILIATION_MAX_DELAY_SECONDS)
                    continue
            try:
                started = await client.start_workflow(
                    workflow,
                    request,
                    id=workflow_id,
                    task_queue=self.config.task_queue,
                    execution_timeout=timedelta(minutes=30),
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
                return _start_result(started, self.config.task_queue)
            except WorkflowAlreadyStartedError:
                # The same deterministic ID exists; describe it on the next pass.
                pass
            except Exception as retry_error:
                diagnostics.append(type(retry_error).__name__)
                if _definitive_start_rejection(retry_error):
                    raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, START_RECONCILIATION_MAX_DELAY_SECONDS)

        _preserve_start_unknown(request, diagnostics)
        raise WorkflowStartUnknownError(
            f"Temporal start acceptance is unresolved for workflow {workflow_id}"
        ) from initial_error

    async def start_listening_profile_setup(
        self,
        *,
        workflow_id: str,
        request: ListeningProfileSetupRequest,
    ) -> WorkflowStartResult:
        from temporalio.client import Client

        client = await Client.connect(
            self.config.address,
            namespace=self.config.namespace,
            data_converter=pydantic_data_converter,
        )
        handle = await client.start_workflow(
            ListeningProfileSetupWorkflow.run,
            request,
            id=workflow_id,
            task_queue=self.config.task_queue,
        )
        return WorkflowStartResult(
            workflow_id=handle.id,
            run_id=handle.result_run_id,
            task_queue=self.config.task_queue,
        )


class RecordingWorkflowStarter:
    """Explicit local/test mode that records queued jobs without Temporal."""

    def __init__(self, config: WorkflowRuntimeConfig | None = None):
        self.config = config or WorkflowRuntimeConfig.from_env()

    async def start_report_generation(
        self,
        *,
        workflow_id: str,
        request: ReportGenerationRequest,
    ) -> WorkflowStartResult:
        return WorkflowStartResult(
            workflow_id=workflow_id,
            run_id=None,
            task_queue=self.config.task_queue,
        )

    async def start_public_listening_sync(
        self,
        *,
        workflow_id: str,
        request,
    ) -> WorkflowStartResult:
        return WorkflowStartResult(
            workflow_id=workflow_id,
            run_id=None,
            task_queue=self.config.task_queue,
        )

    async def start_listening_profile_setup(
        self,
        *,
        workflow_id: str,
        request: ListeningProfileSetupRequest,
    ) -> WorkflowStartResult:
        return WorkflowStartResult(
            workflow_id=workflow_id,
            run_id=None,
            task_queue=self.config.task_queue,
        )


def build_workflow_starter() -> WorkflowStarter:
    mode = (env("RESOUND_WORKFLOW_START_MODE", "temporal") or "temporal").strip().lower()
    if mode in {"record", "record_only", "local"}:
        return RecordingWorkflowStarter()
    return TemporalWorkflowStarter()


def _resolved_public_listening_workflow_id(request) -> str | None:
    organization_id = getattr(request, "organization_id", None)
    brand_id = getattr(request, "brand_id", None)
    workflow_job_id = getattr(request, "workflow_job_id", None)
    if organization_id is None or brand_id is None or workflow_job_id is None:
        return None
    return public_listening_workflow_id(organization_id, brand_id, workflow_job_id)


def _start_result(handle, task_queue: str) -> WorkflowStartResult:
    return WorkflowStartResult(
        workflow_id=handle.id,
        run_id=handle.result_run_id,
        task_queue=task_queue,
    )


def _description_run_id(description) -> str | None:
    info = getattr(description.raw_description, "workflow_execution_info", None)
    execution = getattr(info, "execution", None)
    return getattr(execution, "run_id", None) or None


def _rpc_status(error: Exception):
    from temporalio.service import RPCError

    return error.status if isinstance(error, RPCError) else None


def _definitive_start_rejection(error: Exception) -> bool:
    from temporalio.service import RPCStatusCode

    return _rpc_status(error) in {
        RPCStatusCode.INVALID_ARGUMENT,
        RPCStatusCode.NOT_FOUND,
        RPCStatusCode.PERMISSION_DENIED,
        RPCStatusCode.UNAUTHENTICATED,
    }


def _workflow_confirmed_absent(error: Exception) -> bool:
    from temporalio.service import RPCStatusCode

    return _rpc_status(error) == RPCStatusCode.NOT_FOUND


def _preserve_start_unknown(request, diagnostics: list[str]) -> None:
    workflow_job_id = getattr(request, "workflow_job_id", None)
    organization_id = getattr(request, "organization_id", None)
    brand_id = getattr(request, "brand_id", None)
    owner_token = getattr(request, "owner_token", None)
    if None in {workflow_job_id, organization_id, brand_id} or not owner_token:
        return
    from resound.memory import SqlMemory, WorkflowJobRow

    memory = SqlMemory()
    with memory.session() as session:
        job = session.get(WorkflowJobRow, workflow_job_id)
        if job is not None:
            job.status = "start_unknown"
            job.start_reconciliation_diagnostics = {
                "attempt_error_classes": diagnostics[-20:],
                "workflow_id": _resolved_public_listening_workflow_id(request),
            }
            session.commit()
    memory.renew_workflow_lease(
        organization_id=organization_id,
        brand_id=brand_id,
        owner_token=owner_token,
        ttl_seconds=PUBLIC_LISTENING_START_UNKNOWN_TTL_SECONDS,
    )
