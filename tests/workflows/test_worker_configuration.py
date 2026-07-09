from __future__ import annotations

from resound.workers.temporal import worker_components
from resound.workflows import WorkflowRuntimeConfig


def test_worker_configuration_loads_temporal_settings(monkeypatch):
    monkeypatch.setenv("RESOUND_TEMPORAL_ADDRESS", "temporal.example:7233")
    monkeypatch.setenv("RESOUND_TEMPORAL_NAMESPACE", "prod")
    monkeypatch.setenv("RESOUND_TEMPORAL_TASK_QUEUE", "resound-prod")
    monkeypatch.setenv("RESOUND_WORKER_IDENTITY", "worker-a")

    config = WorkflowRuntimeConfig.from_env()

    assert config.address == "temporal.example:7233"
    assert config.namespace == "prod"
    assert config.task_queue == "resound-prod"
    assert config.worker_identity == "worker-a"


def test_worker_components_do_not_import_fastapi_app():
    components = worker_components()

    assert "SignalProcessingWorkflow" in {workflow.__name__ for workflow in components.workflows}
    assert "RetentionWorkflow" in {workflow.__name__ for workflow in components.workflows}
    assert "process_signal_processing_activity" in {
        activity.__name__ for activity in components.activities
    }
    assert "retention_activity" in {activity.__name__ for activity in components.activities}
