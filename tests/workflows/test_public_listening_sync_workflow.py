from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from resound.agents.signal_triage import SignalTriageResult
from resound.gateway import LLMGatewayConfigError, LLMResponse
from resound.memory import LLMCallRow, RouteRow, SignalRow, SqlMemory
from resound.models import ActionClass, Classification, Route, Sentiment, Severity
from resound.social import ListeningProfile
from resound.tenancy import TenantContext
from resound.workflows.public_listening import PublicListeningSyncRequest, sync_public_listening


class FakeApifyClient:
    def __init__(self, *, item_count: int = 1):
        self.actor_calls: list[str] = []
        self.actor_inputs: list[dict] = []
        self.item_count = item_count

    def run_actor(self, actor_id: str, actor_input: dict):
        self.actor_calls.append(actor_id)
        self.actor_inputs.append(actor_input)
        return {"id": f"run-{actor_id}", "defaultDatasetId": actor_id}

    def fetch_dataset_items(self, dataset_id: str):
        return [
            {
                "id": f"{dataset_id}-{index}",
                "text": f"Checkout errors are blocking purchases {index}.",
                "createdAt": datetime.now(tz=UTC).isoformat(),
                "url": f"https://example.com/post/{index}",
                "author": "user1",
            }
            for index in range(self.item_count)
        ]


class FakeClassifier:
    def classify(self, raw, brand_context):
        from tests.test_pipeline import _fake_response

        return (
            Classification(
                is_about_brand=True,
                area="engineering",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.HIGH,
                action_class=ActionClass.SPRINT,
                summary="Checkout errors",
                confidence=0.9,
            ),
            _fake_response(),
        )


class FatalClassifier:
    def classify(self, raw, brand_context):
        raise LLMGatewayConfigError("missing route stage")


class FakeTriageAgent:
    def run(self, request):
        return SignalTriageResult(
            classification=Classification(
                is_about_brand=True,
                area="engineering",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.HIGH,
                action_class=ActionClass.SPRINT,
                summary="Checkout errors",
                confidence=0.9,
            ),
            classification_prompt="classify prompt",
            classification_response=_response("classification"),
            route=Route(
                owner_id="@eng-on-call",
                destination="@U_ENG",
                matched_rule="agent_route",
                priority="normal",
            ),
            route_prompt="route prompt",
            route_response=_response("route"),
            route_error=None,
            route_latency_ms=None,
            agent_session_id=1,
        )


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used="fake/model",
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.001,
        latency_ms=3.0,
        raw_response={},
    )


def test_public_listening_sync_runs_apify_and_processes_signals(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'public-sync.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    memory.save_listening_profile(
        organization_id=org,
        brand_id=brand.id,
        profile=ListeningProfile(
            brand_slug="acme",
            brand_names=["Acme"],
            keywords=["checkout errors"],
            enabled_sources=["reddit", "youtube_comments"],
        ),
    )
    request = PublicListeningSyncRequest(
        tenant=TenantContext(org, "org-a", team_id=None, user_id=None),
        brand_id=brand.id,
        brand_slug="acme",
        brand_context="Acme sells products online.",
        routing_config={"default_route": "#triage"},
        people_config={"channels": {"#triage": {"slack_channel": "#triage"}}},
    )

    result = sync_public_listening(
        request,
        memory=memory,
        apify_client=FakeApifyClient(),
        classifier=FakeClassifier(),
    )

    with memory.session() as session:
        signals = list(session.execute(select(SignalRow)).scalars())

    assert result.status == "completed"
    assert result.synced_sources == ["reddit", "youtube_comments"]
    assert result.processed_count == 2
    assert len(signals) == 2
    health = memory.list_source_health(org, brand.id)
    assert {row.source_type for row in health} == {"reddit", "youtube_comments"}
    assert all(row.status == "ok" for row in health)


def test_public_listening_sync_filters_sources_and_caps_dataset_items(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'public-sync-cap.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    memory.save_listening_profile(
        organization_id=org,
        brand_id=brand.id,
        profile=ListeningProfile(
            brand_slug="acme",
            brand_names=["Acme"],
            keywords=["checkout errors"],
            enabled_sources=["reddit", "youtube_comments"],
        ),
    )
    request = PublicListeningSyncRequest(
        tenant=TenantContext(org, "org-a", team_id=None, user_id=None),
        brand_id=brand.id,
        brand_slug="acme",
        brand_context="Acme sells products online.",
        routing_config={"default_route": "#triage"},
        people_config={"channels": {"#triage": {"slack_channel": "#triage"}}},
        enabled_sources=["reddit"],
        max_items_per_source=2,
    )
    apify_client = FakeApifyClient(item_count=3)

    result = sync_public_listening(
        request,
        memory=memory,
        apify_client=apify_client,
        classifier=FakeClassifier(),
    )

    with memory.session() as session:
        signals = list(session.execute(select(SignalRow)).scalars())

    assert apify_client.actor_calls == ["solidcode/reddit-scraper"]
    assert apify_client.actor_inputs[0]["maxItems"] == 2
    assert result.synced_sources == ["reddit"]
    assert result.processed_count == 2
    assert len(signals) == 2
    health = memory.list_source_health(org, brand.id)
    assert len(health) == 1
    assert health[0].source_type == "reddit"
    assert health[0].item_count == 2


def test_public_listening_sync_uses_agentic_triage_when_no_classifier_is_injected(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'public-sync-agentic.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    memory.save_listening_profile(
        organization_id=org,
        brand_id=brand.id,
        profile=ListeningProfile(
            brand_slug="acme",
            brand_names=["Acme"],
            keywords=["checkout errors"],
            enabled_sources=["reddit"],
        ),
    )
    request = PublicListeningSyncRequest(
        tenant=TenantContext(org, "org-a", team_id=None, user_id=None),
        brand_id=brand.id,
        brand_slug="acme",
        brand_context="Acme sells products online.",
        routing_config={"default_route": "#triage"},
        people_config={"people": {"@eng-on-call": {"slack": "@U_ENG"}}},
        max_items_per_source=1,
    )

    result = sync_public_listening(
        request,
        memory=memory,
        apify_client=FakeApifyClient(),
        triage_agent=FakeTriageAgent(),
    )

    with memory.session() as session:
        route = session.execute(select(RouteRow)).scalar_one()
        stages = [row.stage for row in session.execute(select(LLMCallRow)).scalars()]

    assert result.status == "completed"
    assert result.processed_count == 1
    assert route.owner_id == "@eng-on-call"
    assert route.matched_rule == "agent_route"
    assert stages == ["classify", "route"]


def test_public_listening_sync_reraises_fatal_llm_configuration_errors(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'public-sync-fatal.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    memory.save_listening_profile(
        organization_id=org,
        brand_id=brand.id,
        profile=ListeningProfile(
            brand_slug="acme",
            brand_names=["Acme"],
            keywords=["checkout errors"],
            enabled_sources=["reddit"],
        ),
    )
    request = PublicListeningSyncRequest(
        tenant=TenantContext(org, "org-a", team_id=None, user_id=None),
        brand_id=brand.id,
        brand_slug="acme",
        brand_context="Acme sells products online.",
        routing_config={"default_route": "#triage"},
        people_config={"channels": {"#triage": {"slack_channel": "#triage"}}},
        max_items_per_source=1,
    )

    with pytest.raises(LLMGatewayConfigError):
        sync_public_listening(
            request,
            memory=memory,
            apify_client=FakeApifyClient(),
            classifier=FatalClassifier(),
        )
