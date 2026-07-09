from __future__ import annotations

from datetime import UTC, datetime

from resound.agents.signal_triage import SignalTriageAgent, SignalTriageRequest
from resound.gateway import JSON_MODE, LLMGateway, LLMGatewayExhaustedError, LLMResponse
from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.tenancy import TenantContext


class FakeGateway(LLMGateway):
    def __init__(self, responses: list[LLMResponse | Exception]):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict | None]] = []

    def complete(
        self,
        stage: str,
        prompt: str,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        self.calls.append((stage, prompt, response_schema))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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


def _request(memory: SqlMemory, org: int, brand_id: int) -> SignalTriageRequest:
    signal_id = memory.record_signal(
        "acme",
        RawSignal(
            source="reddit",
            external_id="p1",
            content="Checkout is broken for enterprise customers.",
            posted_at=datetime.now(tz=UTC),
        ),
        organization_id=org,
        brand_id=brand_id,
    )
    return SignalTriageRequest(
        tenant=TenantContext(org, "org-a", team_id=None, user_id=None),
        brand_id=brand_id,
        brand_slug="acme",
        signal_id=signal_id,
        raw_signal=RawSignal(
            source="reddit",
            external_id="p1",
            content="Checkout is broken for enterprise customers.",
            posted_at=datetime.now(tz=UTC),
        ),
        brand_context="Acme sells checkout software.",
        routing_config={"default_route": "#triage"},
        people_config={
            "people": {"@eng-on-call": {"name": "Eng", "slack": "@U_ENG"}},
            "channels": {"#triage": {"slack_channel": "#triage"}},
        },
    )


def test_signal_triage_agent_classifies_routes_and_records_steps(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'triage-agent.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    gateway = FakeGateway(
        [
            _response(
                '{"is_about_brand": true, "area": "engineering", '
                '"sentiment": "negative", "severity": "high", '
                '"action_class": "sprint", "summary": "Checkout broken", '
                '"confidence": 0.91}'
            ),
            _response(
                '{"owner_id": "@eng-on-call", "priority": "normal", '
                '"notes": "Engineering owns checkout failures.", "confidence": 0.88}'
            ),
        ]
    )

    result = SignalTriageAgent(memory=memory, gateway=gateway).run(
        _request(memory, org, brand.id)
    )

    assert [call[0] for call in gateway.calls] == ["classify", "route"]
    assert [call[2] for call in gateway.calls] == [JSON_MODE, JSON_MODE]
    assert result.classification.area == "engineering"
    assert result.route.owner_id == "@eng-on-call"
    assert result.route.destination == "@U_ENG"
    assert result.agent_session_id is not None
    steps = memory.list_agent_steps(result.agent_session_id)
    assert [step.tool_name for step in steps] == ["classify_signal", "route_signal"]


def test_signal_triage_agent_rejects_invalid_route_owner(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'triage-agent-invalid.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    gateway = FakeGateway(
        [
            _response(
                '{"is_about_brand": true, "area": "product", '
                '"sentiment": "neutral", "severity": "low", '
                '"action_class": "roadmap", "summary": "Feature request", '
                '"confidence": 0.8}'
            ),
            _response(
                '{"owner_id": "@made-up-owner", "priority": "normal", '
                '"notes": "Bad owner", "confidence": 0.5}'
            ),
        ]
    )

    result = SignalTriageAgent(memory=memory, gateway=gateway).run(
        _request(memory, org, brand.id)
    )

    assert result.route.owner_id == "#review-queue"
    assert result.route.matched_rule == "agent_route_fallback"
    assert "invalid owner" in (result.route.notes or "")


def test_signal_triage_agent_rejects_no_owner_for_actionable_signal(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'triage-agent-none.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    gateway = FakeGateway(
        [
            _response(
                '{"is_about_brand": true, "area": "cs", '
                '"sentiment": "negative", "severity": "medium", '
                '"action_class": "sprint", "summary": "Support issue", '
                '"confidence": 0.8}'
            ),
            _response(
                '{"owner_id": "(none)", "priority": "normal", '
                '"notes": "No owner", "confidence": 0.8}'
            ),
        ]
    )

    result = SignalTriageAgent(memory=memory, gateway=gateway).run(
        _request(memory, org, brand.id)
    )

    assert result.route.owner_id == "#review-queue"
    assert result.route.matched_rule == "agent_route_fallback"
    assert "no owner" in (result.route.notes or "")


def test_signal_triage_agent_ignores_off_brand_without_calling_route_model(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'triage-agent-ignore.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    gateway = FakeGateway(
        [
            _response(
                '{"is_about_brand": false, "area": "other", '
                '"sentiment": "neutral", "severity": "low", '
                '"action_class": "ignore", "summary": "Off brand", '
                '"confidence": 0.9}'
            ),
        ]
    )

    result = SignalTriageAgent(memory=memory, gateway=gateway).run(
        _request(memory, org, brand.id)
    )

    assert [call[0] for call in gateway.calls] == ["classify"]
    assert result.route.owner_id == "(none)"
    assert result.route.matched_rule == "ignored_by_classifier"


def test_signal_triage_agent_sends_low_classification_confidence_to_review(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'triage-agent-low-confidence.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    gateway = FakeGateway(
        [
            _response(
                '{"is_about_brand": true, "area": "other", '
                '"sentiment": "mixed", "severity": "medium", '
                '"action_class": "sprint", "summary": "Ambiguous", '
                '"confidence": 0.31}'
            ),
        ]
    )

    result = SignalTriageAgent(memory=memory, gateway=gateway).run(
        _request(memory, org, brand.id)
    )

    assert [call[0] for call in gateway.calls] == ["classify"]
    assert result.route.owner_id == "#review-queue"
    assert result.route.matched_rule == "agent_route_fallback"
    assert "classification confidence" in (result.route.notes or "")


def test_signal_triage_agent_falls_back_when_route_gateway_fails(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'triage-agent-route-error.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    gateway = FakeGateway(
        [
            _response(
                '{"is_about_brand": true, "area": "engineering", '
                '"sentiment": "negative", "severity": "high", '
                '"action_class": "sprint", "summary": "Checkout broken", '
                '"confidence": 0.91}'
            ),
            LLMGatewayExhaustedError("route failed", attempts=2),
        ]
    )

    result = SignalTriageAgent(memory=memory, gateway=gateway).run(
        _request(memory, org, brand.id)
    )

    assert result.route.owner_id == "#review-queue"
    assert result.route.matched_rule == "agent_route_fallback"
    assert result.route_error is not None
    assert result.route_latency_ms is not None
    assert result.agent_session_id is not None
    steps = memory.list_agent_steps(result.agent_session_id)
    assert steps[-1].tool_name == "route_signal"
    assert steps[-1].status == "failed"
