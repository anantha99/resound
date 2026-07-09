"""Workflow runtime configuration and public workflow exports."""

from __future__ import annotations

import socket
from dataclasses import dataclass

from resound.config import env


@dataclass(frozen=True)
class WorkflowRuntimeConfig:
    address: str
    namespace: str
    task_queue: str
    worker_identity: str

    @classmethod
    def from_env(cls) -> WorkflowRuntimeConfig:
        identity = env("RESOUND_WORKER_IDENTITY") or f"resound-worker-{socket.gethostname()}"
        return cls(
            address=env("RESOUND_TEMPORAL_ADDRESS", "127.0.0.1:7233") or "127.0.0.1:7233",
            namespace=env("RESOUND_TEMPORAL_NAMESPACE", "default") or "default",
            task_queue=env("RESOUND_TEMPORAL_TASK_QUEUE", "resound-default") or "resound-default",
            worker_identity=identity,
        )


from resound.workflows.signal_processing import SignalProcessingWorkflow  # noqa: E402

__all__ = ["SignalProcessingWorkflow", "WorkflowRuntimeConfig"]
