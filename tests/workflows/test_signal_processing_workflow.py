from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from resound.agents.signal_triage import SignalTriageResult
from resound.gateway import LLMGatewayExhaustedError, LLMResponse
from resound.memory import LLMCallRow, RouteRow, SqlMemory
from resound.models import ActionClass, Classification, RawSignal, Route, Sentiment, Severity
from resound.workflows.signal_processing import (
    SignalProcessingRequest,
    process_signal,
    signal_processing_steps,
)


def test_signal_processing_steps_order_activity_boundaries():
    request = SignalProcessingRequest(
        brand_slug="acme",
        raw_signal=RawSignal(
            source="reddit",
            external_id="post-1",
            content="Acme launch reaction",
            posted_at=datetime.now(tz=UTC),
        ),
        brand_context="Acme context",
        routing_config={"default_route": "#triage"},
        people_config={},
    )

    steps = signal_processing_steps(request)

    assert steps == [
        "dedupe_signal",
        "record_signal",
        "classify_signal",
        "record_classification",
        "route_signal",
        "record_route",
        "emit_signal_processed",
    ]


class FakeTriageAgent:
    def run(self, request):
        return SignalTriageResult(
            classification=Classification(
                is_about_brand=True,
                area="engineering",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.HIGH,
                action_class=ActionClass.SPRINT,
                summary="Checkout broken",
                confidence=0.92,
            ),
            classification_prompt="classify prompt",
            classification_response=_response("classification"),
            route=Route(
                owner_id="@eng-on-call",
                destination="@U_ENG",
                matched_rule="agent_route",
                priority="normal",
                notes="Engineering owns checkout failures.",
            ),
            route_prompt="route prompt",
            route_response=_response("route"),
            route_error=None,
            route_latency_ms=None,
            agent_session_id=123,
        )


class IgnoringTriageAgent:
    def run(self, request):
        return SignalTriageResult(
            classification=Classification(
                is_about_brand=False,
                area="other",
                sentiment=Sentiment.NEUTRAL,
                severity=Severity.LOW,
                action_class=ActionClass.IGNORE,
                summary="Off brand",
                confidence=0.9,
            ),
            classification_prompt="classify prompt",
            classification_response=_response("classification"),
            route=Route(
                owner_id="(none)",
                destination=None,
                matched_rule="ignored_by_classifier",
                priority="normal",
            ),
            route_prompt="route prompt",
            route_response=None,
            route_error=None,
            route_latency_ms=None,
            agent_session_id=123,
        )


class RouteFailingTriageAgent:
    def run(self, request):
        return SignalTriageResult(
            classification=Classification(
                is_about_brand=True,
                area="engineering",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.HIGH,
                action_class=ActionClass.SPRINT,
                summary="Checkout broken",
                confidence=0.92,
            ),
            classification_prompt="classify prompt",
            classification_response=_response("classification"),
            route=Route(
                owner_id="#review-queue",
                destination="#review-queue",
                matched_rule="agent_route_fallback",
                priority="normal",
                notes="routing gateway error",
            ),
            route_prompt="route prompt",
            route_response=None,
            route_error=LLMGatewayExhaustedError("route failed", attempts=2),
            route_latency_ms=12.0,
            agent_session_id=123,
        )


def test_process_signal_uses_agentic_triage_by_default(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'agentic-process.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    request = SignalProcessingRequest(
        brand_slug="acme",
        raw_signal=RawSignal(
            source="reddit",
            external_id="post-1",
            content="Checkout is broken.",
            posted_at=datetime.now(tz=UTC),
        ),
        brand_context="Acme context",
        routing_config={"default_route": "#triage"},
        people_config={"people": {"@eng-on-call": {"slack": "@U_ENG"}}},
        organization_id=org,
        brand_id=brand.id,
    )

    result = process_signal(request, memory=memory, triage_agent=FakeTriageAgent())

    with memory.session() as session:
        route = session.execute(select(RouteRow)).scalar_one()
        stages = [row.stage for row in session.execute(select(LLMCallRow)).scalars()]

    assert result.status == "processed"
    assert route.owner_id == "@eng-on-call"
    assert route.matched_rule == "agent_route"
    assert stages == ["classify", "route"]


def test_process_signal_agentic_ignore_returns_ignored_status(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'agentic-ignore.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    request = _processing_request(org=org, brand_id=brand.id, external_id="ignore-1")

    result = process_signal(request, memory=memory, triage_agent=IgnoringTriageAgent())

    assert result.status == "ignored"


def test_process_signal_records_route_llm_failure_when_route_agent_falls_back(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'agentic-route-failure.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    request = _processing_request(org=org, brand_id=brand.id, external_id="route-fails-1")

    result = process_signal(request, memory=memory, triage_agent=RouteFailingTriageAgent())

    with memory.session() as session:
        calls = list(session.execute(select(LLMCallRow)).scalars())

    assert result.status == "processed"
    assert [(call.stage, call.success) for call in calls] == [("classify", True), ("route", False)]
    assert calls[-1].error_class == "LLMGatewayExhaustedError"


def test_process_signal_retries_signal_row_without_classification_or_route(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'agentic-partial-retry.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    raw = RawSignal(
        source="reddit",
        external_id="partial-1",
        content="Checkout is broken.",
        posted_at=datetime.now(tz=UTC),
    )
    memory.record_signal("acme", raw, organization_id=org, brand_id=brand.id)
    request = _processing_request(
        org=org,
        brand_id=brand.id,
        external_id="partial-1",
        raw=raw,
    )

    result = process_signal(request, memory=memory, triage_agent=FakeTriageAgent())

    assert result.status == "processed"
    assert result.signal_id is not None


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


def _processing_request(
    *,
    org: int,
    brand_id: int,
    external_id: str,
    raw: RawSignal | None = None,
) -> SignalProcessingRequest:
    return SignalProcessingRequest(
        brand_slug="acme",
        raw_signal=raw
        or RawSignal(
            source="reddit",
            external_id=external_id,
            content="Checkout is broken.",
            posted_at=datetime.now(tz=UTC),
        ),
        brand_context="Acme context",
        routing_config={"default_route": "#triage"},
        people_config={"people": {"@eng-on-call": {"slack": "@U_ENG"}}},
        organization_id=org,
        brand_id=brand_id,
    )
