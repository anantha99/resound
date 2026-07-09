from __future__ import annotations

from resound.memory import SqlMemory
from resound.tenancy import TenantContext
from resound.workflows.listening_setup import ListeningProfileSetupRequest, setup_listening_profile


def test_listening_setup_creates_suggestions_without_saving_hidden_prompt_state(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'setup.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")

    result = setup_listening_profile(
        ListeningProfileSetupRequest(
            tenant=TenantContext(org, "org-a", team_id=None, user_id=None),
            brand_id=brand.id,
            brand_slug="acme",
            brand_names=["Acme"],
            product_names=["Checkout"],
            competitor_names=["Globex"],
        ),
        memory=memory,
    )

    suggestions = memory.list_listening_profile_suggestions(result.profile_id)

    assert result.status == "waiting_for_approval"
    assert {suggestion.suggestion_type for suggestion in suggestions} >= {"keyword", "source"}
    assert all(suggestion.status == "pending" for suggestion in suggestions)
