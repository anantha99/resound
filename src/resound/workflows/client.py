"""Temporal workflow start helpers used by API commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from resound.config import env
from resound.reports.generation import ReportGenerationRequest, ReportGenerationWorkflow
from resound.workflows import WorkflowRuntimeConfig
from resound.workflows.listening_setup import (
    ListeningProfileSetupRequest,
    ListeningProfileSetupWorkflow,
)


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

        client = await Client.connect(self.config.address, namespace=self.config.namespace)
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

        from resound.workflows.public_listening import PublicListeningSyncWorkflow

        client = await Client.connect(self.config.address, namespace=self.config.namespace)
        handle = await client.start_workflow(
            PublicListeningSyncWorkflow.run,
            request,
            id=workflow_id,
            task_queue=self.config.task_queue,
        )
        return WorkflowStartResult(
            workflow_id=handle.id,
            run_id=handle.result_run_id,
            task_queue=self.config.task_queue,
        )

    async def start_listening_profile_setup(
        self,
        *,
        workflow_id: str,
        request: ListeningProfileSetupRequest,
    ) -> WorkflowStartResult:
        from temporalio.client import Client

        client = await Client.connect(self.config.address, namespace=self.config.namespace)
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
