from __future__ import annotations

from resound.reports import REPORT_ROLES, role_template


def test_v1_role_templates_exist_with_fixed_sections():
    assert REPORT_ROLES == ["founder", "product", "marketing", "engineering", "cs"]
    for role in REPORT_ROLES:
        template = role_template(role)
        assert template.role == role
        assert len(template.sections) >= 5
        assert "Emerging Themes" in template.sections
