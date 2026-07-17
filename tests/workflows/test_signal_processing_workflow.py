from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
from sqlalchemy import select

from resound.agents.signal_triage import (
    SignalClassificationResult,
    SignalRouteResult,
    SignalTriageResult,
)
from resound.gateway import (
    DEMO_POPULATION_MODEL_PROFILE,
    LLMGatewayExhaustedError,
    LLMGatewayParseError,
    LLMResponse,
)
from resound.memory import LLMCallRow, RouteRow, SignalRow, SqlMemory
from resound.models import ActionClass, Classification, RawSignal, Route, Sentiment, Severity
from resound.workflows.signal_processing import (
    LeaseLostError,
    SignalProcessingFailpointError,
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


class ClassificationFailingTriageAgent:
    def run(self, request):
        raise LLMGatewayExhaustedError(
            "all classification models returned malformed output",
            attempts=3,
            last_error=LLMGatewayParseError("validation_error", raw_text="{}"),
        )


class SplitStageAgent:
    def __init__(self):
        self.classification_calls = 0
        self.route_calls = 0
        self.route_configs = []

    def classify_only(self, request):
        self.classification_calls += 1
        return SignalClassificationResult(
            classification=Classification(
                is_about_brand=True,
                area="engineering",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.HIGH,
                action_class=ActionClass.SPRINT,
                summary="Checkout broken",
                confidence=0.92,
            ),
            prompt=f"classify with {request.brand_context}",
            response=_response("classification"),
        )

    def route_only(self, request, classification):
        self.route_calls += 1
        self.route_configs.append(
            (request.routing_config, request.people_config, request.model_profile)
        )
        return SignalRouteResult(
            route=Route(
                owner_id="@eng-on-call",
                destination="@U_ENG",
                matched_rule="agent_route",
                priority="normal",
            ),
            prompt="route prompt",
            response=_response("route"),
            error=None,
            latency_ms=1.0,
        )


class BlockingSplitStageAgent(SplitStageAgent):
    def __init__(self):
        super().__init__()
        self.classification_entered = Event()
        self.release_classification = Event()
        self._lock = Lock()

    def classify_only(self, request):
        with self._lock:
            self.classification_calls += 1
        self.classification_entered.set()
        assert self.release_classification.wait(timeout=5)
        return SignalClassificationResult(
            classification=Classification(
                is_about_brand=True,
                area="engineering",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.HIGH,
                action_class=ActionClass.SPRINT,
                summary="Checkout broken",
                confidence=0.92,
            ),
            prompt="classify",
            response=_response("classification"),
        )


class ClaimObservedMemory(SqlMemory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.classification_waiter_observed = Event()

    def acquire_signal_processing_claim(self, **kwargs):
        acquired = super().acquire_signal_processing_claim(**kwargs)
        if kwargs["stage"] == "classification" and not acquired:
            self.classification_waiter_observed.set()
        return acquired

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


def test_all_malformed_classifications_return_processing_failure(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'classification-failure.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    request = _processing_request(org=org, brand_id=brand.id, external_id="malformed-1")
    request = replace(request, model_profile=DEMO_POPULATION_MODEL_PROFILE)

    result = process_signal(
        request,
        memory=memory,
        triage_agent=ClassificationFailingTriageAgent(),
    )

    with memory.session() as session:
        calls = list(session.execute(select(LLMCallRow)).scalars())
        routes = list(session.execute(select(RouteRow)).scalars())

    assert result.status == "failed"
    assert result.processing_state == "failed"
    assert result.error_class == "LLMGatewayExhaustedError"
    assert "malformed output" in (result.error_message or "")
    assert [(call.stage, call.success) for call in calls] == [("classify", False)]
    assert routes == []


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

    assert result.status == "resumed"
    assert result.processing_state == "resumed"
    assert result.resumed_count == 1
    assert result.signal_id is not None


def test_concurrent_workers_claim_external_stages_once(tmp_path):
    memory = ClaimObservedMemory(database_url=f"sqlite:///{tmp_path / 'stage-claims.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    request = _processing_request(org=org, brand_id=brand.id, external_id="claim-race-1")
    agent = BlockingSplitStageAgent()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(process_signal, request, memory=memory, triage_agent=agent)
        assert agent.classification_entered.wait(timeout=5)
        second = executor.submit(process_signal, request, memory=memory, triage_agent=agent)
        assert memory.classification_waiter_observed.wait(timeout=5)
        assert agent.classification_calls == 1
        agent.release_classification.set()
        results = [first.result(timeout=5), second.result(timeout=5)]

    assert agent.classification_calls == 1
    assert agent.route_calls == 1
    assert sorted(result.processing_state for result in results) == ["processed", "resumed"]


def test_classification_commit_resume_routes_once_with_original_inline_config(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'stage-resume.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    agent = SplitStageAgent()
    request = replace(
        _processing_request(org=org, brand_id=brand.id, external_id="resume-1"),
        model_profile="original-profile",
        metadata={"failpoint": "after_classification_commit"},
    )

    with pytest.raises(SignalProcessingFailpointError, match="after_classification_commit"):
        process_signal(request, memory=memory, triage_agent=agent)

    with memory.session() as session:
        session.get(type(brand), brand.id).source_config = {"routing": "mutated"}
        session.commit()
    result = process_signal(
        replace(request, metadata={}),
        memory=memory,
        triage_agent=agent,
    )

    assert result.status == "resumed"
    assert agent.classification_calls == 1
    assert agent.route_calls == 1
    assert agent.route_configs == [
        (
            request.routing_config,
            request.people_config,
            "original-profile",
        )
    ]


def test_route_response_without_commit_is_retried_but_route_commit_is_not(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'route-resume.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    agent = SplitStageAgent()
    request = _processing_request(org=org, brand_id=brand.id, external_id="route-resume-1")

    with pytest.raises(SignalProcessingFailpointError, match="after_route_response"):
        process_signal(
            replace(request, metadata={"failpoint": "after_route_response"}),
            memory=memory,
            triage_agent=agent,
        )
    assert process_signal(request, memory=memory, triage_agent=agent).status == "resumed"
    assert process_signal(request, memory=memory, triage_agent=agent).status == "duplicate"
    assert agent.classification_calls == 1
    assert agent.route_calls == 2


def test_stale_owner_is_rejected_before_signal_or_llm_side_effect(tmp_path):
    memory = SqlMemory(database_url=f"sqlite:///{tmp_path / 'owner-loss.db'}")
    org = memory.ensure_organization("org-a", "Org A")
    brand = memory.ensure_brand(org, "acme", "Acme")
    old_job = memory.create_workflow_job(
        workflow_id="old",
        workflow_type="public_listening_sync",
        organization_id=org,
        brand_id=brand.id,
    )
    new_job = memory.create_workflow_job(
        workflow_id="new",
        workflow_type="public_listening_sync",
        organization_id=org,
        brand_id=brand.id,
    )
    now = datetime.utcnow()
    memory.acquire_workflow_lease(
        organization_id=org,
        brand_id=brand.id,
        workflow_job_id=old_job,
        owner_token="old-owner",
        now=now - timedelta(seconds=121),
    )
    memory.acquire_workflow_lease(
        organization_id=org,
        brand_id=brand.id,
        workflow_job_id=new_job,
        owner_token="new-owner",
        now=now,
    )
    agent = SplitStageAgent()
    request = replace(
        _processing_request(org=org, brand_id=brand.id, external_id="owner-loss-1"),
        owner_token="old-owner",
    )

    with pytest.raises(LeaseLostError):
        process_signal(request, memory=memory, triage_agent=agent)
    assert agent.classification_calls == 0
    with memory.session() as session:
        assert session.execute(select(SignalRow)).scalars().all() == []


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
