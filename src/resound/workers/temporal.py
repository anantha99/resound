"""Temporal worker bootstrap for Resound workflows."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from temporalio.contrib.pydantic import pydantic_data_converter

from resound.reports.generation import ReportGenerationWorkflow, generate_report_activity
from resound.workflows import SignalProcessingWorkflow, WorkflowRuntimeConfig
from resound.workflows.listening_setup import (
    ListeningProfileSetupWorkflow,
    listening_profile_setup_activity,
)
from resound.workflows.public_listening import (
    PublicListeningSyncWorkflow,
    public_listening_finalizer_activity,
    public_listening_source_activity,
    public_listening_sync_activity,
)
from resound.workflows.retention import RetentionWorkflow, retention_activity
from resound.workflows.signal_processing import process_signal_processing_activity


@dataclass(frozen=True)
class WorkerComponents:
    workflows: list[type]
    activities: list[Callable]


def worker_components() -> WorkerComponents:
    return WorkerComponents(
        workflows=[
            SignalProcessingWorkflow,
            ReportGenerationWorkflow,
            PublicListeningSyncWorkflow,
            ListeningProfileSetupWorkflow,
            RetentionWorkflow,
        ],
        activities=[
            process_signal_processing_activity,
            generate_report_activity,
            public_listening_sync_activity,
            public_listening_source_activity,
            public_listening_finalizer_activity,
            listening_profile_setup_activity,
            retention_activity,
        ],
    )


async def run_worker(config: WorkflowRuntimeConfig | None = None) -> None:
    from temporalio.client import Client
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker

    runtime = config or WorkflowRuntimeConfig.from_env()
    executor = ThreadPoolExecutor(
        max_workers=runtime.activity_threads,
        thread_name_prefix="resound-activity",
    )
    try:
        components = worker_components()
        client = await Client.connect(
            runtime.address,
            namespace=runtime.namespace,
            data_converter=pydantic_data_converter,
        )
        worker = Worker(
            client,
            task_queue=runtime.task_queue,
            workflows=components.workflows,
            activities=components.activities,
            activity_executor=executor,
            max_concurrent_activities=runtime.activity_threads,
            identity=runtime.worker_identity,
            workflow_runner=UnsandboxedWorkflowRunner(),
        )
        await worker.run()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
