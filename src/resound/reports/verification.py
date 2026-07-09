"""Report quality gates before customer exposure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from resound.agents.role_report import RoleReportDraft
from resound.reports import ReportTemplate

ReportRunStatus = Literal["held_for_review", "ready_for_customer_release", "rejected"]


@dataclass(frozen=True)
class ReportVerification:
    status: ReportRunStatus
    issues: list[str]
    internal_usefulness_rating: float | None = None


def verify_report_draft(
    draft: RoleReportDraft,
    *,
    template: ReportTemplate,
    allowed_signal_ids: set[int],
    internal_usefulness_rating: float | None = None,
) -> ReportVerification:
    issues: list[str] = []
    section_titles = [section.title for section in draft.sections]
    if section_titles != template.sections:
        issues.append("fixed_section_schema_mismatch")

    draft_citations = set(draft.citations)
    section_citations = {
        signal_id for section in draft.sections for signal_id in section.citation_ids
    }
    invalid_citations = sorted((draft_citations | section_citations) - allowed_signal_ids)
    if invalid_citations:
        issues.append("citation_outside_tenant_brand_scope")

    if not draft.low_data and not draft_citations:
        issues.append("missing_report_citations")
    if not draft.low_data:
        uncited_sections = [section.title for section in draft.sections if not section.citation_ids]
        if uncited_sections:
            issues.append("section_missing_citations")

    if draft.low_data and not _has_low_data_caveat(draft):
        issues.append("missing_low_data_caveat")

    if issues:
        return ReportVerification(
            status="rejected",
            issues=issues,
            internal_usefulness_rating=internal_usefulness_rating,
        )
    if internal_usefulness_rating is not None and internal_usefulness_rating >= 4:
        return ReportVerification(
            status="ready_for_customer_release",
            issues=[],
            internal_usefulness_rating=internal_usefulness_rating,
        )
    return ReportVerification(
        status="held_for_review",
        issues=[],
        internal_usefulness_rating=internal_usefulness_rating,
    )


def _has_low_data_caveat(draft: RoleReportDraft) -> bool:
    text = "\n".join(section.body.lower() for section in draft.sections)
    return "low-data" in text or "no matching stored signals" in text
