from __future__ import annotations

from datetime import UTC, datetime

from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.reports.generation import ReportGenerationRequest, generate_report
from resound.tenancy import TenantContext


def test_report_generation_persists_report_run_with_citations_and_markdown(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'reports.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="p1",
            content="Users say onboarding is confusing.",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org,
        brand_id=brand.id,
    )
    config_id = memory.save_report_config(
        organization_id=org,
        brand_id=brand.id,
        team_id=7,
        role="product",
        name="Weekly Product Report",
        filters={"source": "reddit"},
        timeframe="7d",
    )

    result = generate_report(
        ReportGenerationRequest(
            tenant=TenantContext(org, "org-a", team_id=7, user_id=None),
            brand_id=brand.id,
            brand_slug="acme",
            report_config_id=config_id,
            role="product",
            timeframe="7d",
        ),
        memory=memory,
    )

    run = memory.get_report_run(result.report_run_id)

    assert run is not None
    assert run.status == "held_for_review"
    assert run.role == "product"
    assert "# Product Report" in run.markdown
    assert memory.list_report_citations(result.report_run_id)
