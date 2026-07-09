from __future__ import annotations

from datetime import UTC, datetime

from resound.agents.role_report import RoleReportAgent
from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.reports import role_template
from resound.tenancy import TenantContext


def test_role_report_agent_uses_fixed_template_and_citations(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'role-agent.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    signal_id = memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="p1",
            content="Checkout errors are blocking purchases.",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org,
        brand_id=brand.id,
    )

    report = RoleReportAgent(memory).generate(
        tenant=TenantContext(org, "org-a", team_id=3, user_id=None),
        brand_id=brand.id,
        brand_slug="acme",
        template=role_template("engineering"),
        timeframe="7d",
    )

    assert [section.title for section in report.sections] == role_template("engineering").sections
    assert signal_id in report.citations
    assert report.low_data is False
