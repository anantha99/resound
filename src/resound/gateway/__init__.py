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
from resound.gateway.models_config import ModelsConfig, StageConfig, load_models_config
from resound.gateway.openrouter import OpenRouterGateway

__all__ = [
    # Core abstractions
    "LLMGateway",
    "LLMResponse",
    "OpenRouterGateway",
    # Config
    "load_models_config",
    "StageConfig",
    "ModelsConfig",
    # Factory
    "build_gateway",
    # Exceptions (per design #13 — hierarchy under LLMGatewayError)
    "LLMGatewayError",
    "LLMGatewayConfigError",
    "LLMGatewayAuthError",
    "LLMGatewayExhaustedError",
    "LLMGatewayTimeoutError",
    "LLMGatewayParseError",
]


def build_gateway(brand_slug: str) -> OpenRouterGateway:
    """Build an OpenRouterGateway configured for a specific brand.

    Loads ``config/models.yaml`` global defaults merged with brand-specific
    overrides from ``brands/<brand_slug>/models.yaml``. This is the public
    API; use ``OpenRouterGateway(config=..., client=...)`` directly for tests.
    """
    return OpenRouterGateway(config=load_models_config(brand_slug))
