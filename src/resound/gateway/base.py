"""Gateway abstraction contract.

Every LLM call in Resound flows through an :class:`LLMGateway`. The gateway
owns model selection, retry/backoff, fallback chains, and cost tracking; the
caller passes only the *stage* (a logical role like ``"classify"``) plus the
prompt and gets back an :class:`LLMResponse`.

See ``docs/design_decisions.md`` ("Task 1") for the locked rationale behind
this surface. In short:

* ``stage`` is a plain string so new stages can be added without code changes.
* ``response_schema`` is a flag-only sentinel meaning "request JSON mode";
  the gateway does not validate the response against it (callers already
  parse with their own Pydantic models).
* ``temperature`` / ``max_tokens`` / ``model_override`` are intentionally
  absent — ``StageConfig`` is the single source of truth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Result of a successful gateway call.

    Lean by design: this struct holds only what the gateway can produce on
    its own. Audit-trail fields (``stage``, ``prompt_hash``, ``timestamp``,
    ``signal_id``) live in the ``llm_calls`` table written by the pipeline,
    not here.

    ``was_fallback`` and ``attempt_count`` were added per design decision
    #29 (Task 3 amendment): the audit trail needs to know whether this row
    was served by the stage's primary model or a fallback, and how many
    HTTP attempts were burned getting here. Computing these from
    ``ModelsConfig`` after the fact is lossy when config drifts.
    """

    content: str
    model_used: str  # the model that actually returned (may be a fallback)
    tokens_in: int
    tokens_out: int
    cost_usd: float | None = None  # None when OpenRouter omits usage.cost
    latency_ms: float
    raw_response: dict[str, Any] = Field(default_factory=dict)
    was_fallback: bool = False
    attempt_count: int = 1


class LLMGateway(ABC):
    """Abstract gateway. One instance per brand (see Pipeline wiring)."""

    @abstractmethod
    def complete(
        self,
        stage: str,
        prompt: str,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        """Run a completion for ``stage``.

        ``stage`` is looked up in the gateway's ``ModelsConfig`` to resolve
        model, temperature, max_tokens, fallbacks, and timeout.

        ``response_schema`` is a flag-only sentinel: when not ``None``, the
        gateway requests JSON-mode output (with prompt-suffix fallback for
        models that lack native support). The schema itself is not enforced.

        Raises :class:`LLMGatewayConfigError` for unknown stages,
        :class:`LLMGatewayAuthError` for credential failures,
        :class:`LLMGatewayExhaustedError` when retries+fallbacks are spent,
        :class:`LLMGatewayTimeoutError` when the per-stage wall clock fires,
        :class:`LLMGatewayParseError` when JSON extraction ultimately fails.
        """

    def complete_validated(
        self,
        stage: str,
        prompt: str,
        *,
        response_schema: dict | None = None,
        validator: Callable[[str], object],
    ) -> LLMResponse:
        """Complete and validate content before considering the call successful.

        The default keeps custom/test gateways compatible. Gateways with model
        fallback support override this so validation failure advances to the
        next configured model rather than escaping after model selection.
        """
        response = self.complete(stage, prompt, response_schema)
        validator(response.content)
        return response


class LLMGatewayError(Exception):
    """Base for all gateway errors. Pipeline catches this broadly to skip
    a bad signal and continue. Subclasses ``LLMGatewayConfigError`` and
    ``LLMGatewayAuthError`` are FATAL — pipeline does NOT catch those."""


class LLMGatewayConfigError(LLMGatewayError):
    """Misconfigured gateway: unknown stage, malformed models.yaml, etc.
    Fatal — should crash the worker so the operator notices."""


class LLMGatewayAuthError(LLMGatewayError):
    """Credential failure (401/403). Fatal — retrying won't help."""


class LLMGatewayExhaustedError(LLMGatewayError):
    """All retries and fallback models were exhausted without success."""

    def __init__(
        self,
        message: str,
        attempts: int,
        last_error: Exception | None = None,
        model_used: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float | None = None,
        latency_ms: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error
        self.model_used = model_used
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd
        self.latency_ms = latency_ms


class LLMGatewayTimeoutError(LLMGatewayError):
    """Per-stage wall-clock cap (``StageConfig.timeout_s``) was exceeded."""


class LLMGatewayParseError(LLMGatewayError):
    """JSON extraction failed even after the prompt-suffix fallback."""

    def __init__(
        self,
        message: str,
        raw_text: str,
        *,
        model_used: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float | None = None,
        latency_ms: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.model_used = model_used
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.cost_usd = cost_usd
        self.latency_ms = latency_ms
