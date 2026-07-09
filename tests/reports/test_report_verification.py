from __future__ import annotations

from resound.agents.role_report import ReportSectionDraft, RoleReportDraft
from resound.reports import role_template
from resound.reports.verification import verify_report_draft


def test_report_verifier_rejects_malformed_section_schema():
    template = role_template("product")
    draft = _draft(sections=[ReportSectionDraft("Wrong", "Body", [1])], citations=[1])

    result = verify_report_draft(draft, template=template, allowed_signal_ids={1})

    assert result.status == "rejected"
    assert "fixed_section_schema_mismatch" in result.issues


def test_report_verifier_rejects_out_of_scope_citation():
    template = role_template("product")
    draft = _draft(
        sections=[ReportSectionDraft(title, "Body", [99]) for title in template.sections],
        citations=[99],
    )

    result = verify_report_draft(draft, template=template, allowed_signal_ids={1})

    assert result.status == "rejected"
    assert "citation_outside_tenant_brand_scope" in result.issues


def test_report_verifier_holds_low_rated_valid_report():
    template = role_template("product")
    draft = _draft(
        sections=[
            ReportSectionDraft(title, "Claim with citation", [1])
            for title in template.sections
        ],
        citations=[1],
    )

    result = verify_report_draft(
        draft,
        template=template,
        allowed_signal_ids={1},
        internal_usefulness_rating=3.5,
    )

    assert result.status == "held_for_review"
    assert result.issues == []


def test_report_verifier_accepts_low_data_report_with_caveat():
    template = role_template("product")
    draft = _draft(
        sections=[
            ReportSectionDraft(title, "No matching stored signals were found. Low-data caveat.", [])
            for title in template.sections
        ],
        citations=[],
        low_data=True,
    )

    result = verify_report_draft(draft, template=template, allowed_signal_ids=set())

    assert result.status == "held_for_review"
    assert result.issues == []


def _draft(
    *,
    sections: list[ReportSectionDraft],
    citations: list[int],
    low_data: bool = False,
) -> RoleReportDraft:
    return RoleReportDraft(
        role="product",
        timeframe="7d",
        sections=sections,
        citations=citations,
        low_data=low_data,
        source_freshness={},
        agent_session_id=1,
    )
