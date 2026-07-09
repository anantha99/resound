from __future__ import annotations

from datetime import UTC, datetime

from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.tenancy import TenantContext


def test_tenant_brands_are_scoped_by_organization(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'tenants.db'}")
    org_a = memory.ensure_organization("org-a", "Org A")
    org_b = memory.ensure_organization("org-b", "Org B")
    brand_a = memory.ensure_brand(org_a, "acme", "Acme A")
    memory.ensure_brand(org_b, "acme", "Acme B")

    context = TenantContext(
        organization_id=org_a,
        organization_slug="org-a",
        team_id=None,
        user_id=None,
    )

    brands = memory.list_brands_for_tenant(context)

    assert [(brand.slug, brand.display_name) for brand in brands] == [("acme", "Acme A")]
    assert brand_a.organization_id == org_a


def test_tenant_signal_reads_do_not_cross_organizations(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'tenant-signals.db'}")
    org_a = memory.ensure_organization("org-a", "Org A")
    org_b = memory.ensure_organization("org-b", "Org B")
    brand_a = memory.ensure_brand(org_a, "acme", "Acme A")
    brand_b = memory.ensure_brand(org_b, "acme", "Acme B")

    memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="a1",
            content="Org A signal",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org_a,
        brand_id=brand_a.id,
    )
    memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="b1",
            content="Org B signal",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org_b,
        brand_id=brand_b.id,
    )

    context = TenantContext(
        organization_id=org_a,
        organization_slug="org-a",
        team_id=None,
        user_id=None,
    )

    rows = memory.list_signals_for_tenant(context, brand_slug="acme")

    assert [row.content for row in rows] == ["Org A signal"]
