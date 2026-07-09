"""Durable signal-processing workflow and activities."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Literal

from sqlalchemy import select

from resound.agents.signal_triage import SignalTriageAgent, SignalTriageRequest
from resound.classifiers import make_fallback_classification
from resound.core.classifier import Classifier
from resound.gateway import LLMGatewayAuthError, LLMGatewayConfigError, LLMGatewayError
from resound.memory import ClassificationRow, RouteRow, SignalRow, SqlMemory
from resound.models import RawSignal
from resound.prompts.classify import build_classify_prompt
from resound.routers import RulesRouter
from resound.tenancy import TenantContext
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
        return SignalProcessingResult(status="duplicate", dedupe_key=dedupe_key)
    if existing and (existing.classification_id is not None or existing.route_id is not None):
        return SignalProcessingResult(status="duplicate", dedupe_key=dedupe_key)

    signal_id = existing.signal_id if existing else memory.record_signal(
        request.brand_slug,
        request.raw_signal,
        organization_id=request.organization_id,
        brand_id=request.brand_id,
    )
    if classifier is not None:
        classification, route = _classify_and_route_with_legacy_classifier(
            request,
            memory,
            signal_id,
            classifier,
            router,
        )
    else:
        classification, route = _classify_and_route_with_agent(
            request,
            memory,
            signal_id,
            triage_agent,
            router,
        )

    classification_id = memory.record_classification(signal_id, classification)
    route_id = memory.record_route(signal_id, classification_id, route)
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
        classification = make_fallback_classification(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        classification = make_fallback_classification(f"unexpected: {type(exc).__name__}")
    return classification, router.route(request.raw_signal, classification)


def _existing_signal_state(memory: SqlMemory, dedupe_key: str) -> ExistingSignalState | None:
    with memory.session() as session:
        row = session.execute(
            select(SignalRow.id, ClassificationRow.id, RouteRow.id)
            .outerjoin(ClassificationRow, ClassificationRow.signal_id == SignalRow.id)
            .outerjoin(RouteRow, RouteRow.signal_id == SignalRow.id)
            .where(SignalRow.dedupe_key == dedupe_key)
        ).one_or_none()
    if row is None:
        return None
    signal_id, classification_id, route_id = row
    return ExistingSignalState(
        signal_id=signal_id,
        classification_id=classification_id,
        route_id=route_id,
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
        classification = make_fallback_classification(f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        classification = make_fallback_classification(f"unexpected: {type(exc).__name__}")
    return classification, router.route(request.raw_signal, classification)


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
