from __future__ import annotations

from resound.agents.team_directory import build_team_directory


def test_team_directory_merges_brand_people_channels_and_generic_defaults():
    directory = build_team_directory(
        people_config={
            "people": {"@product-lead": {"name": "Product", "slack": "@U_PRODUCT"}},
            "channels": {"#custom-triage": {"description": "Custom intake"}},
        },
        routing_config={
            "default_route": "#custom-triage",
            "rules": [{"name": "billing", "route_to": "@billing-owner"}],
        },
    )

    assert "#custom-triage" in directory.allowed_owner_ids
    assert "@product-lead" in directory.allowed_owner_ids
    assert "@eng-on-call" in directory.allowed_owner_ids
    assert "@billing-owner" in directory.allowed_owner_ids
    assert directory.default_owner_id == "#custom-triage"
    assert directory.review_owner_id == "#review-queue"
    assert directory.resolve("@product-lead") == "@U_PRODUCT"


def test_team_directory_prompt_context_lists_owner_descriptions():
    directory = build_team_directory(people_config={}, routing_config={})

    context = directory.prompt_context()

    assert "#triage" in context
    assert "@product-lead" in context
    assert "Roadmap" in context
