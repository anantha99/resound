from __future__ import annotations

from resound.memory import SqlMemory


def test_workflow_jobs_record_stage_events_for_dashboard(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'workflow-observability.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    job_id = memory.create_workflow_job(
        workflow_id="signal-processing-1",
        workflow_type="SignalProcessingWorkflow",
        organization_id=org,
        brand_id=brand.id,
    )

    memory.record_workflow_event(
        workflow_job_id=job_id,
        stage="classify_signal",
        status="succeeded",
        message="Classified one signal",
    )

    events = memory.list_workflow_events(job_id)

    assert events[0].stage == "classify_signal"
    assert events[0].status == "succeeded"
    assert events[0].message == "Classified one signal"
