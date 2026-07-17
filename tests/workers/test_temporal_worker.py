from __future__ import annotations

import asyncio
import inspect

import pytest

from resound.workers import temporal
from resound.workflows import WorkflowRuntimeConfig


def _runtime(activity_threads: int = 7) -> WorkflowRuntimeConfig:
    return WorkflowRuntimeConfig(
        address="temporal.test:7233",
        namespace="default",
        task_queue="task-4",
        worker_identity="test-worker",
        activity_threads=activity_threads,
    )


def test_registered_blocking_activity_audit_is_entirely_synchronous():
    components = temporal.worker_components()

    assert {activity.__name__ for activity in components.activities} >= {
        "generate_report_activity",
        "process_signal_processing_activity",
        "public_listening_sync_activity",
        "public_listening_source_activity",
        "public_listening_finalizer_activity",
        "listening_profile_setup_activity",
        "retention_activity",
    }
    assert all(not inspect.iscoroutinefunction(activity) for activity in components.activities)


def test_activity_thread_configuration_is_validated(monkeypatch):
    monkeypatch.setenv("RESOUND_TEMPORAL_ACTIVITY_THREADS", "4")
    with pytest.raises(ValueError, match="between 5 and 64"):
        WorkflowRuntimeConfig.from_env()

    monkeypatch.setenv("RESOUND_TEMPORAL_ACTIVITY_THREADS", "17")
    assert WorkflowRuntimeConfig.from_env().activity_threads == 17


@pytest.mark.parametrize("worker_error", [None, RuntimeError("worker failed")])
def test_worker_aligns_executor_and_concurrency_and_always_shuts_down(monkeypatch, worker_error):
    events: list[object] = []

    class FakeExecutor:
        def __init__(self, *, max_workers, thread_name_prefix):
            events.append(("executor", max_workers, thread_name_prefix))

        def shutdown(self, *, wait, cancel_futures):
            events.append(("shutdown", wait, cancel_futures))

    class FakeClient:
        @staticmethod
        async def connect(address, *, namespace, data_converter):
            events.append(("connect", address, namespace, data_converter))
            return object()

    class FakeWorker:
        def __init__(self, _client, **kwargs):
            events.append(("worker", kwargs))

        async def run(self):
            if worker_error:
                raise worker_error

    monkeypatch.setattr(temporal, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr("temporalio.client.Client", FakeClient)
    monkeypatch.setattr("temporalio.worker.Worker", FakeWorker)

    if worker_error:
        with pytest.raises(RuntimeError, match="worker failed"):
            asyncio.run(temporal.run_worker(_runtime()))
    else:
        asyncio.run(temporal.run_worker(_runtime()))

    worker_kwargs = next(item[1] for item in events if item[0] == "worker")
    assert worker_kwargs["max_concurrent_activities"] == 7
    assert worker_kwargs["activity_executor"].__class__ is FakeExecutor
    assert worker_kwargs["workflow_runner"].__class__.__name__ == "UnsandboxedWorkflowRunner"
    assert events[-1] == ("shutdown", True, True)
