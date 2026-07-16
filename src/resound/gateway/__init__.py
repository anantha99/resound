"""Gateway abstraction layer for all LLM calls.

Centralizes model selection, retry logic with exponential backoff, fallback
chains, and cost tracking through OpenRouter. See ``docs/design_decisions.md``
("Task 1") for the locked design rationale.
"""

from __future__ import annotations

from resound.gateway.base import (
    LLMGateway,
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayError,
    LLMGatewayExhaustedError,
    LLMGatewayParseError,
    LLMGatewayTimeoutError,
    LLMResponse,
)
from resound.gateway.models_config import (
    DEMO_POPULATION_MODEL_PROFILE,
    DEMO_POPULATION_MODEL_PROFILES,
    DEMO_POPULATION_RELIABLE_MODEL_PROFILE,
    ModelsConfig,
    StageConfig,
    load_models_config,
)
from resound.gateway.openrouter import OpenRouterGateway

JSON_MODE: dict = {}
"""Sentinel for ``LLMGateway.complete(response_schema=JSON_MODE)``.

Per design #2 the gateway treats ``response_schema`` as a presence flag —
non-None means "request JSON mode" and the schema body is not validated.
Callers pass this named sentinel instead of a bare ``{}`` so the intent is
self-documenting at the call site (per design #38).
"""

__all__ = [
    # Core abstractions
    "LLMGateway",
    "LLMResponse",
    "OpenRouterGateway",
    # Config
    "load_models_config",
    "StageConfig",
    "ModelsConfig",
    "DEMO_POPULATION_MODEL_PROFILE",
    "DEMO_POPULATION_RELIABLE_MODEL_PROFILE",
    "DEMO_POPULATION_MODEL_PROFILES",
    # Factory
    "build_gateway",
    # Sentinels
    "JSON_MODE",
    # Exceptions (per design #13 — hierarchy under LLMGatewayError)
    "LLMGatewayError",
    "LLMGatewayConfigError",
    "LLMGatewayAuthError",
    "LLMGatewayExhaustedError",
    "LLMGatewayTimeoutError",
    "LLMGatewayParseError",
]


def build_gateway(brand_slug: str, profile: str | None = None) -> OpenRouterGateway:
    """Build an OpenRouterGateway configured for a specific brand.

    Loads ``config/models.yaml`` global defaults merged with brand-specific
    overrides from ``brands/<brand_slug>/models.yaml``. A named profile is
    applied last when explicitly selected by a scoped workflow. This is the
    public API; use ``OpenRouterGateway(config=..., client=...)`` directly for
    tests.
    """
    return OpenRouterGateway(config=load_models_config(brand_slug, profile=profile))
