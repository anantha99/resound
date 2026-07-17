"""Durable signal-processing workflow and activities."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import select

from resound.agents.signal_triage import SignalTriageAgent, SignalTriageRequest
from resound.classifiers import make_fallback_classification
from resound.core.classifier import Classifier
from resound.gateway import (
    DEMO_POPULATION_MODEL_PROFILES,
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayError,
    LLMGatewayExhaustedError,
    LLMGatewayParseError,
)
from resound.memory import ClassificationRow, RouteRow, SignalRow, SqlMemory
from resound.models import Classification, RawSignal
from resound.prompts.classify import build_classify_prompt
from resound.routers import RulesRouter
from resound.tenancy import TenantContext
from resound.workflows.leases import PUBLIC_LISTENING_WORKFLOW_KIND
from resound.workflows.temporal_compat import activity, workflow

SignalProcessingStatus = Literal["processed", "duplicate", "ignored", "failed"]


@dataclass(frozen=True)
class SignalProcessingRequest:
    brand_slug: str
    raw_signal: RawSignal
    brand_context: str
    routing_config: dict[str, Any]
    people_config: dict[str, Any]
    organization_id: int | None = None
    brand_id: int | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    model_profile: str | None = None
    owner_token: str | None = None
    workflow_kind: str = PUBLIC_LISTENING_WORKFLOW_KIND


@dataclass(frozen=True)
class SignalProcessingResult:
    status: SignalProcessingStatus
    dedupe_key: str
    signal_id: int | None = None
    classification_id: int | None = None
    route_id: int | None = None
    error_class: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ExistingSignalState:
    signal_id: int
    classification_id: int | None
    route_id: int | None


class LeaseLostError(RuntimeError):
    pass


class SignalProcessingFailpointError(RuntimeError):
    pass


def signal_processing_steps(_: SignalProcessingRequest) -> list[str]:
    return [
        "dedupe_signal",
        "record_signal",
        "classify_signal",
        "record_classification",
        "route_signal",
        "record_route",
        "emit_signal_processed",
    ]


def process_signal(
    request: SignalProcessingRequest,
    *,
    memory: SqlMemory | None = None,
    classifier: Classifier | None = None,
    triage_agent: SignalTriageAgent | None = None,
    heartbeat: Callable[[str, int], None] | None = None,
) -> SignalProcessingResult:
    memory = memory or SqlMemory()
    router = RulesRouter(request.routing_config, request.people_config)
    dedupe_key = memory.signal_dedupe_key(
        request.brand_slug,
        request.raw_signal,
        organization_id=request.organization_id,
        brand_id=request.brand_id,
    )

    existing = _existing_signal_state(memory, dedupe_key)
    if existing and existing.classification_id is not None and existing.route_id is not None:
        return SignalProcessingResult(
            status="duplicate",
            dedupe_key=dedupe_key,
            signal_id=existing.signal_id,
            classification_id=existing.classification_id,
            route_id=existing.route_id,
        )

    if existing is None:
        _assert_owner(request, memory)
        signal_id = memory.record_signal(
            request.brand_slug,
            request.raw_signal,
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
        _checkpoint(heartbeat, "signal_committed", signal_id)
        _trip_failpoint(request, "after_signal_commit")
        existing = _existing_signal_state(memory, dedupe_key, signal_id=signal_id)
    else:
        signal_id = existing.signal_id

    classification_record = memory.load_classification(signal_id)
    cached_route = None
    if classification_record is None:
        _assert_owner(request, memory)
        try:
            if classifier is not None:
                classification = _classify_with_legacy_classifier(
                    request, memory, signal_id, classifier
                )
            else:
                classification, cached_route = _classify_with_agent(
                    request, memory, signal_id, triage_agent
                )
        except (LLMGatewayConfigError, LLMGatewayAuthError):
            raise
        except LLMGatewayError as exc:
            return _failed_processing_result(dedupe_key, signal_id, exc)
        classification_id = memory.record_classification(signal_id, classification)
        classification_record = memory.load_classification(signal_id)
        if classification_record is None:
            raise RuntimeError("classification commit could not be reloaded")
        classification_id, classification = classification_record
        _checkpoint(heartbeat, "classification_committed", signal_id)
        _trip_failpoint(request, "after_classification_commit")
    else:
        classification_id, classification = classification_record

    state = _existing_signal_state(memory, dedupe_key, signal_id=signal_id)
    if state and state.route_id is not None:
        return SignalProcessingResult(
            status="duplicate",
            dedupe_key=dedupe_key,
            signal_id=signal_id,
            classification_id=classification_id,
            route_id=state.route_id,
        )

    _assert_owner(request, memory)
    try:
        if cached_route is not None:
            route = cached_route
        elif classifier is not None:
            route = router.route(request.raw_signal, classification)
        else:
            route = _route_with_agent(request, memory, signal_id, classification, triage_agent)
    except (LLMGatewayConfigError, LLMGatewayAuthError):
        raise
    except LLMGatewayError as exc:
        return _failed_processing_result(dedupe_key, signal_id, exc)
    _trip_failpoint(request, "after_route_response")
    route_id = memory.record_route(signal_id, classification_id, route)
    _checkpoint(heartbeat, "route_committed", signal_id)
    _trip_failpoint(request, "after_route_commit")
    status: SignalProcessingStatus = (
        "ignored" if route.matched_rule == "ignored_by_classifier" else "processed"
    )
    return SignalProcessingResult(
        status=status,
        dedupe_key=dedupe_key,
        signal_id=signal_id,
        classification_id=classification_id,
        route_id=route_id,
    )


def _assert_owner(request: SignalProcessingRequest, memory: SqlMemory) -> None:
    if request.owner_token is None:
        return
    if request.organization_id is None or request.brand_id is None:
        raise LeaseLostError("owner-token protected processing requires organization and brand")
    if not memory.renew_workflow_lease(
        organization_id=request.organization_id,
        brand_id=request.brand_id,
        owner_token=request.owner_token,
        workflow_kind=request.workflow_kind,
    ):
        raise LeaseLostError("public-listening workflow lease was lost")


def _checkpoint(
    heartbeat: Callable[[str, int], None] | None,
    stage: str,
    signal_id: int,
) -> None:
    if heartbeat is not None:
        heartbeat(stage, signal_id)


def _trip_failpoint(request: SignalProcessingRequest, stage: str) -> None:
    if request.metadata.get("failpoint") == stage:
        raise SignalProcessingFailpointError(stage)


def _failed_processing_result(
    dedupe_key: str,
    signal_id: int,
    error: LLMGatewayError,
) -> SignalProcessingResult:
    return SignalProcessingResult(
        status="failed",
        dedupe_key=dedupe_key,
        signal_id=signal_id,
        error_class=type(error).__name__,
        error_message=str(error),
    )


def _classify_and_route_with_legacy_classifier(
    request: SignalProcessingRequest,
    memory: SqlMemory,
    signal_id: int,
    classifier: Classifier,
    router: RulesRouter,
):
    prompt = build_classify_prompt(request.raw_signal, request.brand_context)
    started = time.perf_counter()
    try:
        classification, response = classifier.classify(request.raw_signal, request.brand_context)
        memory.record_llm_call(
            brand_slug=request.brand_slug,
            signal_id=signal_id,
            stage="classify",
            prompt=prompt,
            response=response,
            was_fallback=response.was_fallback,
            attempt_count=response.attempt_count,
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
    except (LLMGatewayConfigError, LLMGatewayAuthError):
        raise
    except LLMGatewayError as exc:
        memory.record_llm_failure(
            brand_slug=request.brand_slug,
            signal_id=signal_id,
            stage="classify",
            prompt=prompt,
            error=exc,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            attempt_count=getattr(exc, "attempts", 1),
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
        if (
            request.model_profile in DEMO_POPULATION_MODEL_PROFILES
            and _is_classification_validation_failure(exc)
        ):
            raise
        classification = make_fallback_classification(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        classification = make_fallback_classification(f"unexpected: {type(exc).__name__}")
    return classification, router.route(request.raw_signal, classification)


def _classify_with_legacy_classifier(
    request: SignalProcessingRequest,
    memory: SqlMemory,
    signal_id: int,
    classifier: Classifier,
) -> Classification:
    classification, _ = _classify_and_route_with_legacy_classifier(
        request,
        memory,
        signal_id,
        classifier,
        RulesRouter(request.routing_config, request.people_config),
    )
    return classification


def _existing_signal_state(
    memory: SqlMemory,
    dedupe_key: str,
    *,
    signal_id: int | None = None,
) -> ExistingSignalState | None:
    with memory.session() as session:
        statement = (
            select(SignalRow.id, ClassificationRow.id, RouteRow.id)
            .outerjoin(ClassificationRow, ClassificationRow.signal_id == SignalRow.id)
            .outerjoin(RouteRow, RouteRow.signal_id == SignalRow.id)
        )
        identity_clause = (
            SignalRow.id == signal_id
            if signal_id is not None
            else SignalRow.dedupe_key == dedupe_key
        )
        statement = statement.where(identity_clause)
        row = session.execute(statement).one_or_none()
    if row is None:
        return None
    signal_id, classification_id, route_id = row
    return ExistingSignalState(
        signal_id=signal_id,
        classification_id=classification_id,
        route_id=route_id,
    )


def _classify_with_agent(
    request: SignalProcessingRequest,
    memory: SqlMemory,
    signal_id: int,
    triage_agent: SignalTriageAgent | None,
) -> tuple[Classification, Any | None]:
    agent = triage_agent or SignalTriageAgent(memory=memory)
    agent_request = _agent_request(request, signal_id)
    if not hasattr(agent, "classify_only"):
        return _classify_and_route_with_agent(
            request,
            memory,
            signal_id,
            agent,
            RulesRouter(request.routing_config, request.people_config),
        )
    started = time.perf_counter()
    try:
        result = agent.classify_only(agent_request)
    except (LLMGatewayConfigError, LLMGatewayAuthError):
        raise
    except LLMGatewayError as exc:
        memory.record_llm_failure(
            brand_slug=request.brand_slug,
            signal_id=signal_id,
            stage="classify",
            prompt=build_classify_prompt(request.raw_signal, request.brand_context),
            error=exc,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            attempt_count=getattr(exc, "attempts", 1),
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
        raise
    memory.record_llm_call(
        brand_slug=request.brand_slug,
        signal_id=signal_id,
        stage="classify",
        prompt=result.prompt,
        response=result.response,
        was_fallback=result.response.was_fallback,
        attempt_count=result.response.attempt_count,
        organization_id=request.organization_id,
        brand_id=request.brand_id,
    )
    return result.classification, None


def _route_with_agent(
    request: SignalProcessingRequest,
    memory: SqlMemory,
    signal_id: int,
    classification: Classification,
    triage_agent: SignalTriageAgent | None,
):
    agent = triage_agent or SignalTriageAgent(memory=memory)
    if not hasattr(agent, "route_only"):
        return RulesRouter(request.routing_config, request.people_config).route(
            request.raw_signal, classification
        )
    result = agent.route_only(_agent_request(request, signal_id), classification)
    if result.response is not None:
        memory.record_llm_call(
            brand_slug=request.brand_slug,
            signal_id=signal_id,
            stage="route",
            prompt=result.prompt,
            response=result.response,
            was_fallback=result.response.was_fallback,
            attempt_count=result.response.attempt_count,
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
    elif result.error is not None:
        memory.record_llm_failure(
            brand_slug=request.brand_slug,
            signal_id=signal_id,
            stage="route",
            prompt=result.prompt,
            error=result.error,
            latency_ms=result.latency_ms or 0.0,
            attempt_count=getattr(result.error, "attempts", 1),
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
    return result.route


def _agent_request(request: SignalProcessingRequest, signal_id: int) -> SignalTriageRequest:
    return SignalTriageRequest(
        tenant=_tenant_from_request(request),
        brand_id=request.brand_id,
        brand_slug=request.brand_slug,
        signal_id=signal_id,
        raw_signal=request.raw_signal,
        brand_context=request.brand_context,
        routing_config=request.routing_config,
        people_config=request.people_config,
        model_profile=request.model_profile,
    )


def _classify_and_route_with_agent(
    request: SignalProcessingRequest,
    memory: SqlMemory,
    signal_id: int,
    triage_agent: SignalTriageAgent | None,
    router: RulesRouter,
):
    prompt = build_classify_prompt(request.raw_signal, request.brand_context)
    started = time.perf_counter()
    agent = triage_agent or SignalTriageAgent(memory=memory)
    try:
        result = agent.run(
            SignalTriageRequest(
                tenant=_tenant_from_request(request),
                brand_id=request.brand_id,
                brand_slug=request.brand_slug,
                signal_id=signal_id,
                raw_signal=request.raw_signal,
                brand_context=request.brand_context,
                routing_config=request.routing_config,
                people_config=request.people_config,
                model_profile=request.model_profile,
            )
        )
        memory.record_llm_call(
            brand_slug=request.brand_slug,
            signal_id=signal_id,
            stage="classify",
            prompt=result.classification_prompt,
            response=result.classification_response,
            was_fallback=result.classification_response.was_fallback,
            attempt_count=result.classification_response.attempt_count,
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
        if result.route_response is not None:
            memory.record_llm_call(
                brand_slug=request.brand_slug,
                signal_id=signal_id,
                stage="route",
                prompt=result.route_prompt,
                response=result.route_response,
                was_fallback=result.route_response.was_fallback,
                attempt_count=result.route_response.attempt_count,
                organization_id=request.organization_id,
                brand_id=request.brand_id,
            )
        elif result.route_error is not None:
            memory.record_llm_failure(
                brand_slug=request.brand_slug,
                signal_id=signal_id,
                stage="route",
                prompt=result.route_prompt,
                error=result.route_error,
                latency_ms=result.route_latency_ms or 0.0,
                attempt_count=getattr(result.route_error, "attempts", 1),
                organization_id=request.organization_id,
                brand_id=request.brand_id,
            )
        return result.classification, result.route
    except (LLMGatewayConfigError, LLMGatewayAuthError):
        raise
    except LLMGatewayError as exc:
        memory.record_llm_failure(
            brand_slug=request.brand_slug,
            signal_id=signal_id,
            stage="classify",
            prompt=prompt,
            error=exc,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            attempt_count=getattr(exc, "attempts", 1),
            organization_id=request.organization_id,
            brand_id=request.brand_id,
        )
        if (
            request.model_profile in DEMO_POPULATION_MODEL_PROFILES
            and _is_classification_validation_failure(exc)
        ):
            raise
        classification = make_fallback_classification(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        classification = make_fallback_classification(f"unexpected: {type(exc).__name__}")
    return classification, router.route(request.raw_signal, classification)


def _is_classification_validation_failure(error: LLMGatewayError) -> bool:
    if isinstance(error, LLMGatewayParseError):
        return True
    return isinstance(error, LLMGatewayExhaustedError) and isinstance(
        error.last_error,
        LLMGatewayParseError,
    )


def _tenant_from_request(request: SignalProcessingRequest) -> TenantContext | None:
    if request.organization_id is None:
        return None
    organization_slug = str(request.metadata.get("organization_slug") or request.organization_id)
    return TenantContext(
        request.organization_id,
        organization_slug,
        team_id=None,
        user_id=None,
    )


@activity.defn
async def process_signal_processing_activity(
    request: SignalProcessingRequest,
) -> SignalProcessingResult:
    return process_signal(request)


@workflow.defn
class SignalProcessingWorkflow:
    @workflow.run
    async def run(self, request: SignalProcessingRequest) -> SignalProcessingResult:
        return await workflow.execute_activity(
            process_signal_processing_activity,
            request,
            start_to_close_timeout=timedelta(minutes=5),
        )
