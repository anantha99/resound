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
    activity_threads: int = 10

    @classmethod
    def from_env(cls) -> WorkflowRuntimeConfig:
        identity = env("RESOUND_WORKER_IDENTITY") or f"resound-worker-{socket.gethostname()}"
        raw_activity_threads = env("RESOUND_TEMPORAL_ACTIVITY_THREADS", "10") or "10"
        try:
            activity_threads = int(raw_activity_threads)
        except ValueError as exc:
            raise ValueError("RESOUND_TEMPORAL_ACTIVITY_THREADS must be an integer") from exc
        if not 5 <= activity_threads <= 64:
            raise ValueError("RESOUND_TEMPORAL_ACTIVITY_THREADS must be between 5 and 64")
        return cls(
            address=env("RESOUND_TEMPORAL_ADDRESS", "127.0.0.1:7233") or "127.0.0.1:7233",
            namespace=env("RESOUND_TEMPORAL_NAMESPACE", "default") or "default",
            task_queue=env("RESOUND_TEMPORAL_TASK_QUEUE", "resound-default") or "resound-default",
            worker_identity=identity,
            activity_threads=activity_threads,
        )


from resound.workflows.signal_processing import SignalProcessingWorkflow  # noqa: E402

__all__ = ["SignalProcessingWorkflow", "WorkflowRuntimeConfig"]
