"""LangGraph-backed signal classification and routing agents."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from resound.agents.runtime import AgentRuntime
from resound.agents.team_directory import TeamDirectory, build_team_directory
from resound.classifiers.openrouter import (
    parse_classification_response,
    parse_classification_response_strict,
)
from resound.gateway import (
    DEMO_POPULATION_MODEL_PROFILES,
    JSON_MODE,
    LLMGateway,
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayError,
    LLMResponse,
    build_gateway,
)
from resound.memory import SqlMemory
from resound.models import ActionClass, Classification, RawSignal, Route
from resound.prompts.classify import build_classify_prompt
from resound.prompts.route import build_route_prompt
from resound.tenancy import TenantContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SignalTriageRequest:
    tenant: TenantContext | None
    brand_id: int | None
    brand_slug: str
    signal_id: int
    raw_signal: RawSignal
    brand_context: str
    routing_config: dict[str, Any]
    people_config: dict[str, Any]
    model_profile: str | None = None


@dataclass(frozen=True)
class SignalTriageResult:
    classification: Classification
    classification_prompt: str
    classification_response: LLMResponse
    route: Route
    route_prompt: str
    route_response: LLMResponse | None
    route_error: LLMGatewayError | None
    route_latency_ms: float | None
    agent_session_id: int | None


@dataclass(frozen=True)
class SignalClassificationResult:
    classification: Classification
    prompt: str
    response: LLMResponse


@dataclass(frozen=True)
class SignalRouteResult:
    route: Route
    prompt: str
    response: LLMResponse | None
    error: LLMGatewayError | None
    latency_ms: float | None


class SignalTriageAgent:
    """Classify and route one signal through a small LangGraph state graph."""

    def __init__(
        self,
        *,
        memory: SqlMemory,
        gateway: LLMGateway | None = None,
    ):
        self.memory = memory
        self.gateway = gateway
        self._resolved_gateway: tuple[tuple[str, str | None], LLMGateway] | None = None

    def run(self, request: SignalTriageRequest) -> SignalTriageResult:
        gateway = self.gateway or self._gateway_for(request)
        session_id = self._create_session(request)
        runtime = AgentRuntime.linear(
            [
                ("classify_signal", lambda state: self._classify(gateway, state)),
                ("route_signal", lambda state: self._route(gateway, state)),
            ]
        )
        try:
            state = runtime.invoke(
                {
                    "request": request,
                    "session_id": session_id,
                    "team_directory": build_team_directory(
                        people_config=request.people_config,
                        routing_config=request.routing_config,
                    ),
                }
            )
        except Exception:
            if session_id is not None:
                self.memory.update_agent_session_status(session_id, "failed")
            raise
        if session_id is not None:
            self.memory.update_agent_session_status(session_id, "completed")
        return SignalTriageResult(
            classification=state["classification"],
            classification_prompt=state["classification_prompt"],
            classification_response=state["classification_response"],
            route=state["route"],
            route_prompt=state["route_prompt"],
            route_response=state.get("route_response"),
            route_error=state.get("route_error"),
            route_latency_ms=state.get("route_latency_ms"),
            agent_session_id=session_id,
        )

    def classify_only(self, request: SignalTriageRequest) -> SignalClassificationResult:
        """Run only classification so its commit can precede any routing side effect."""

        gateway = self.gateway or self._gateway_for(request)
        state = self._classify(gateway, {"request": request, "session_id": None})
        return SignalClassificationResult(
            classification=state["classification"],
            prompt=state["classification_prompt"],
            response=state["classification_response"],
        )

    def route_only(
        self,
        request: SignalTriageRequest,
        classification: Classification,
    ) -> SignalRouteResult:
        """Route a committed classification using only the request's inline config."""

        gateway = self.gateway or self._gateway_for(request)
        state = self._route(
            gateway,
            {
                "request": request,
                "session_id": None,
                "classification": classification,
                "team_directory": build_team_directory(
                    people_config=request.people_config,
                    routing_config=request.routing_config,
                ),
            },
        )
        return SignalRouteResult(
            route=state["route"],
            prompt=state["route_prompt"],
            response=state.get("route_response"),
            error=state.get("route_error"),
            latency_ms=state.get("route_latency_ms"),
        )

    def _gateway_for(self, request: SignalTriageRequest) -> LLMGateway:
        key = (request.brand_slug, request.model_profile)
        if self._resolved_gateway is None or self._resolved_gateway[0] != key:
            self._resolved_gateway = (
                key,
                build_gateway(request.brand_slug, profile=request.model_profile),
            )
        return self._resolved_gateway[1]

    def _create_session(self, request: SignalTriageRequest) -> int | None:
        if request.tenant is None:
            return None
        return self.memory.create_agent_session(
            organization_id=request.tenant.organization_id,
            brand_id=request.brand_id,
            agent_type="signal_triage",
            user_goal=f"Classify and route signal {request.signal_id} for {request.brand_slug}",
        )

    def _classify(self, gateway: LLMGateway, state: dict[str, Any]) -> dict[str, Any]:
        request: SignalTriageRequest = state["request"]
        prompt = build_classify_prompt(request.raw_signal, request.brand_context)
        if request.model_profile not in DEMO_POPULATION_MODEL_PROFILES:
            response = gateway.complete(stage="classify", prompt=prompt, response_schema=JSON_MODE)
            classification = parse_classification_response(response.content)
        else:
            response = gateway.complete_validated(
                stage="classify",
                prompt=prompt,
                response_schema=JSON_MODE,
                validator=parse_classification_response_strict,
            )
            classification = parse_classification_response_strict(response.content)
        _record_agent_step(
            self.memory,
            state.get("session_id"),
            tool_name="classify_signal",
            input_json={"signal_id": request.signal_id, "source": request.raw_signal.source},
            output_json={
                "area": classification.area,
                "severity": classification.severity.value,
                "action_class": classification.action_class.value,
                "confidence": classification.confidence,
                "model_used": response.model_used,
            },
        )
        return {
            **state,
            "classification": classification,
            "classification_prompt": prompt,
            "classification_response": response,
        }

    def _route(self, gateway: LLMGateway, state: dict[str, Any]) -> dict[str, Any]:
        request: SignalTriageRequest = state["request"]
        classification: Classification = state["classification"]
        team_directory: TeamDirectory = state["team_directory"]
        prompt = build_route_prompt(
            raw=request.raw_signal,
            classification=classification,
            brand_context=request.brand_context,
            routing_config=request.routing_config,
            team_directory=team_directory,
        )

        if classification.action_class == ActionClass.IGNORE or not classification.is_about_brand:
            route = Route(
                owner_id="(none)",
                destination=None,
                matched_rule="ignored_by_classifier",
                priority="normal",
                notes="Classification marked this signal as ignore / off-brand.",
            )
            _record_agent_step(
                self.memory,
                state.get("session_id"),
                tool_name="route_signal",
                input_json={"signal_id": request.signal_id},
                output_json={"owner_id": route.owner_id, "matched_rule": route.matched_rule},
            )
            return {**state, "route": route, "route_prompt": prompt}

        if classification.confidence < 0.5:
            route = _fallback_route(
                team_directory,
                "classification confidence below review threshold",
            )
            _record_agent_step(
                self.memory,
                state.get("session_id"),
                tool_name="route_signal",
                input_json={"signal_id": request.signal_id},
                output_json={"owner_id": route.owner_id, "matched_rule": route.matched_rule},
            )
            return {**state, "route": route, "route_prompt": prompt}

        started = time.perf_counter()
        try:
            response = gateway.complete(stage="route", prompt=prompt, response_schema=JSON_MODE)
        except (LLMGatewayConfigError, LLMGatewayAuthError):
            raise
        except LLMGatewayError as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            route = _fallback_route(team_directory, f"routing gateway error: {type(exc).__name__}")
            _record_agent_step(
                self.memory,
                state.get("session_id"),
                tool_name="route_signal",
                input_json={"signal_id": request.signal_id},
                output_json={"owner_id": route.owner_id, "matched_rule": route.matched_rule},
                status="failed",
                error_message=str(exc),
            )
            return {
                **state,
                "route": route,
                "route_prompt": prompt,
                "route_error": exc,
                "route_latency_ms": latency_ms,
            }

        route = _parse_route_response(response.content, team_directory)
        if route.owner_id == "(none)":
            route = _fallback_route(
                team_directory,
                "routing agent selected no owner for an on-brand actionable signal",
            )
        _record_agent_step(
            self.memory,
            state.get("session_id"),
            tool_name="route_signal",
            input_json={"signal_id": request.signal_id},
            output_json={
                "owner_id": route.owner_id,
                "priority": route.priority,
                "matched_rule": route.matched_rule,
                "model_used": response.model_used,
            },
        )
        return {
            **state,
            "route": route,
            "route_prompt": prompt,
            "route_response": response,
        }


def _parse_route_response(text: str, team_directory: TeamDirectory) -> Route:
    match = re.search(r"\{.*\}", text.strip(), re.DOTALL)
    if not match:
        return _fallback_route(team_directory, "routing agent returned no JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return _fallback_route(team_directory, f"routing JSON parse error: {exc}")

    owner_id = str(data.get("owner_id") or "").strip()
    if owner_id not in team_directory.allowed_owner_ids:
        return _fallback_route(team_directory, f"routing agent selected invalid owner: {owner_id}")
    confidence = _optional_float(data.get("confidence"))
    if confidence is not None and confidence < 0.5 and owner_id != team_directory.review_owner_id:
        return _fallback_route(team_directory, "routing agent confidence below review threshold")
    priority = str(data.get("priority") or "normal").strip().lower()
    if priority not in {"normal", "immediate"}:
        priority = "normal"
    notes = str(data.get("notes") or "Agent selected route.").strip()[:500]
    if confidence is not None:
        notes = f"{notes} route_confidence={confidence}"
    return Route(
        owner_id=owner_id,
        destination=team_directory.resolve(owner_id),
        matched_rule="agent_route",
        priority=priority,
        notes=notes,
    )


def _fallback_route(team_directory: TeamDirectory, reason: str) -> Route:
    owner_id = team_directory.review_owner_id or team_directory.default_owner_id
    return Route(
        owner_id=owner_id,
        destination=team_directory.resolve(owner_id),
        matched_rule="agent_route_fallback",
        priority="normal",
        notes=reason[:500],
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_agent_step(
    memory: SqlMemory,
    agent_session_id: int | None,
    *,
    tool_name: str,
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    status: str = "succeeded",
    error_message: str | None = None,
) -> None:
    if agent_session_id is None:
        return
    memory.record_agent_step(
        agent_session_id=agent_session_id,
        tool_name=tool_name,
        input_json=input_json,
        output_json=output_json,
        status=status,
        error_message=error_message,
    )
