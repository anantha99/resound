"""Temporal worker bootstrap for Resound workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from resound.reports.generation import ReportGenerationWorkflow, generate_report_activity
from resound.workflows import SignalProcessingWorkflow, WorkflowRuntimeConfig
from resound.workflows.listening_setup import (
    ListeningProfileSetupWorkflow,
    listening_profile_setup_activity,
)
from resound.workflows.public_listening import (
    PublicListeningSyncWorkflow,
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
            listening_profile_setup_activity,
            retention_activity,
        ],
    )


async def run_worker(config: WorkflowRuntimeConfig | None = None) -> None:
    from temporalio.client import Client
    from temporalio.worker import Worker

    runtime = config or WorkflowRuntimeConfig.from_env()
    components = worker_components()
    client = await Client.connect(runtime.address, namespace=runtime.namespace)
    worker = Worker(
        client,
        task_queue=runtime.task_queue,
        workflows=components.workflows,
        activities=components.activities,
        identity=runtime.worker_identity,
    )
    await worker.run()
