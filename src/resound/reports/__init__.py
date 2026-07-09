"""Role-personalized report templates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportTemplate:
    role: str
    display_name: str
    sections: list[str]


REPORT_ROLES = ["founder", "product", "marketing", "engineering", "cs"]

_TEMPLATES: dict[str, ReportTemplate] = {
    "founder": ReportTemplate(
        role="founder",
        display_name="Founder",
        sections=[
            "Executive Summary",
            "Biggest Risks",
            "Strongest Opportunities",
            "Brand Perception Shifts",
            "Recommended Leadership Actions",
            "Emerging Themes",
        ],
    ),
    "product": ReportTemplate(
        role="product",
        display_name="Product",
        sections=[
            "Top Product Complaints",
            "Feature Requests",
            "UX Friction",
            "Roadmap Implications",
            "Representative Signals",
            "Emerging Themes",
        ],
    ),
    "marketing": ReportTemplate(
        role="marketing",
        display_name="Marketing",
        sections=[
            "Sentiment Shifts",
            "Repeated Customer Phrases",
            "Content Opportunities",
            "Competitor Comparisons",
            "Campaign Reactions",
            "Emerging Themes",
        ],
    ),
    "engineering": ReportTemplate(
        role="engineering",
        display_name="Engineering",
        sections=[
            "Suspected Defects",
            "Severity Clusters",
            "Repro Hints",
            "Affected Platforms Or Features",
            "Recommended Investigation Queue",
            "Emerging Themes",
        ],
    ),
    "cs": ReportTemplate(
        role="cs",
        display_name="CS",
        sections=[
            "Top Support Questions",
            "Confusion Drivers",
            "Urgent Complaints",
            "Suggested Macros",
            "Escalation Candidates",
            "Emerging Themes",
        ],
    ),
}


def role_template(role: str) -> ReportTemplate:
    normalized = role.strip().lower()
    try:
        return _TEMPLATES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown report role: {role}") from exc
