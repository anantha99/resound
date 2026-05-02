"""OpenRouter-backed LLM gateway.

Per-stage retry/backoff, fallback chain, JSON-mode try-and-detect, and
per-stage wall-clock cap — all per ``docs/design_decisions.md`` (Task 1).

Control-flow notes:
* Each model gets a fresh budget of ``MAX_ATTEMPTS_PER_MODEL`` attempts.
* Transient errors (timeouts, 429, 5xx, connection blips) retry within the
  current model with ``2**attempt`` backoff (2s, 4s).
* Fallback errors (404, 413, 422, OpenRouter "no available provider") move
  to the next model in the chain.
* Auth errors (401/403) and bad-request errors (400 not related to JSON
  mode) raise immediately as fatal — pipeline does NOT catch these.
* JSON-mode unsupported (400 with ``response_format``/``json_object`` in
  the message) is a soft retry: cache the model in
  ``_no_json_mode_models`` and re-call the same model with a prompt
  suffix + regex extraction.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, NoReturn

import openai
from openai import OpenAI

from resound.config import env
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
from resound.gateway.models_config import ModelsConfig, StageConfig

logger = logging.getLogger(__name__)

MAX_ATTEMPTS_PER_MODEL = 3
JSON_PROMPT_SUFFIX = "\n\nRespond with JSON only, no additional prose."
NO_PROVIDER_MARKERS = ("no available provider", "no allowed providers")
JSON_MODE_ERROR_MARKERS = ("response_format", "json_object")
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class _RetryWithinModel(Exception):
    """Internal: transient error — retry the same model after backoff."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


class _TryNextModel(Exception):
    """Internal: error means give up on this model and try the next."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


class _JsonModeNotSupported(Exception):
    """Internal: model rejected ``response_format``; retry with prompt suffix."""

    def __init__(self, original: Exception) -> None:
        super().__init__(str(original))
        self.original = original


class OpenRouterGateway(LLMGateway):
    """LLMGateway implementation routing through OpenRouter.

    Constructor accepts a ``client`` for tests so retry/fallback paths can be
    exercised without monkeypatching ``openai.OpenAI``.
    """

    def __init__(
        self,
        config: ModelsConfig,
        api_key: str | None = None,
        http_referer: str | None = None,
        app_title: str | None = None,
        client: OpenAI | None = None,
    ) -> None:
        self.config = config
        self._no_json_mode_models: set[str] = set()

        if client is not None:
            self.client = client
            return

        api_key = api_key or env("OPENROUTER_API_KEY")
        if not api_key:
            raise LLMGatewayConfigError(
                "OPENROUTER_API_KEY is required (set in env or pass api_key=)"
            )
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            default_headers={
                "HTTP-Referer": http_referer
                or env("OPENROUTER_APP_URL", "https://github.com/resound"),
                "X-Title": app_title or env("OPENROUTER_APP_NAME", "Resound"),
            },
        )

    def complete(
        self,
        stage: str,
        prompt: str,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        stage_cfg = self.config.get_stage_config(stage)
        deadline = time.perf_counter() + stage_cfg.timeout_s
        models = [stage_cfg.model, *stage_cfg.fallbacks]
        total_attempts = 0
        last_error: Exception | None = None

        for model in models:
            for attempt in range(1, MAX_ATTEMPTS_PER_MODEL + 1):
                total_attempts += 1
                self._check_deadline(deadline, stage, stage_cfg.timeout_s)

                try:
                    return self._call_once(
                        model, stage_cfg, prompt, response_schema, deadline
                    )
                except _RetryWithinModel as wrap:
                    last_error = wrap.original
                    if attempt >= MAX_ATTEMPTS_PER_MODEL:
                        break  # exhausted on this model — try next
                    self._backoff(attempt, deadline, stage, stage_cfg.timeout_s)
                    continue
                except _TryNextModel as wrap:
                    last_error = wrap.original
                    break  # try next model

        raise LLMGatewayExhaustedError(
            f"Stage {stage!r}: all {len(models)} model(s) failed after "
            f"{total_attempts} attempt(s). Last error: {last_error!r}",
            attempts=total_attempts,
        )

    # --- internals -------------------------------------------------------

    def _check_deadline(self, deadline: float, stage: str, total_s: float) -> None:
        if time.perf_counter() > deadline:
            raise LLMGatewayTimeoutError(
                f"Stage {stage!r} exceeded {total_s}s wall-clock cap"
            )

    def _backoff(
        self, attempt: int, deadline: float, stage: str, total_s: float
    ) -> None:
        sleep_s = float(2**attempt)  # attempt=1 → 2s, attempt=2 → 4s
        if time.perf_counter() + sleep_s > deadline:
            raise LLMGatewayTimeoutError(
                f"Stage {stage!r}: backoff would exceed {total_s}s wall-clock cap"
            )
        time.sleep(sleep_s)

    def _call_once(
        self,
        model: str,
        stage_cfg: StageConfig,
        prompt: str,
        response_schema: dict | None,
        deadline: float,
    ) -> LLMResponse:
        if response_schema is None:
            return self._do_call(
                model, stage_cfg, prompt,
                json_mode=False, prompt_suffix=False, deadline=deadline,
            )

        # JSON output requested
        if model in self._no_json_mode_models:
            return self._do_call(
                model, stage_cfg, prompt,
                json_mode=False, prompt_suffix=True, deadline=deadline,
            )

        try:
            return self._do_call(
                model, stage_cfg, prompt,
                json_mode=True, prompt_suffix=False, deadline=deadline,
            )
        except _JsonModeNotSupported:
            self._no_json_mode_models.add(model)
            logger.warning(
                "%s does not support native JSON mode; caching and retrying "
                "with prompt-suffix fallback",
                model,
            )
            return self._do_call(
                model, stage_cfg, prompt,
                json_mode=False, prompt_suffix=True, deadline=deadline,
            )

    def _do_call(
        self,
        model: str,
        stage_cfg: StageConfig,
        prompt: str,
        *,
        json_mode: bool,
        prompt_suffix: bool,
        deadline: float,
    ) -> LLMResponse:
        final_prompt = prompt + JSON_PROMPT_SUFFIX if prompt_suffix else prompt

        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": final_prompt}],
            "temperature": stage_cfg.temperature,
            "max_tokens": stage_cfg.max_tokens,
            "extra_body": {"usage": {"include": True}},
        }
        if json_mode:
            request_kwargs["response_format"] = {"type": "json_object"}

        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            raise LLMGatewayTimeoutError(
                f"Stage timeout exceeded before call to {model}"
            )
        request_kwargs["timeout"] = remaining

        start = time.perf_counter()
        try:
            response = self.client.chat.completions.create(**request_kwargs)
        except Exception as exc:
            self._raise_classified(exc, model)
        latency_ms = (time.perf_counter() - start) * 1000.0

        text = response.choices[0].message.content or ""

        # Always run defensive regex extraction when JSON output expected.
        if json_mode or prompt_suffix:
            match = _JSON_OBJECT_RE.search(text)
            if match is None:
                raise LLMGatewayParseError(
                    f"No JSON object found in response from {model}",
                    raw_text=text,
                )
            content = match.group(0)
        else:
            content = text

        usage = response.usage
        tokens_in = getattr(usage, "prompt_tokens", 0) if usage else 0
        tokens_out = getattr(usage, "completion_tokens", 0) if usage else 0
        cost = getattr(usage, "cost", None) if usage else None
        if cost is None:
            logger.warning("OpenRouter returned no usage.cost for %s", model)

        return LLMResponse(
            content=content,
            model_used=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            latency_ms=latency_ms,
            raw_response=response.model_dump(),
        )

    def _raise_classified(self, exc: Exception, model: str) -> NoReturn:
        """Translate an SDK exception into the right control-flow or public
        exception, then raise. Never returns."""
        msg = str(exc)
        msg_lower = msg.lower()

        # Connection-level transients first (no status code attached)
        if isinstance(exc, openai.APITimeoutError | openai.APIConnectionError):
            raise _RetryWithinModel(exc) from exc
        if isinstance(exc, openai.RateLimitError):
            raise _RetryWithinModel(exc) from exc

        if isinstance(exc, openai.APIStatusError):
            sc: int | None = getattr(exc, "status_code", None)

            # OpenRouter "no available provider" can come back as 5xx — treat
            # as fallback regardless of status (decision #5).
            if any(marker in msg_lower for marker in NO_PROVIDER_MARKERS):
                raise _TryNextModel(exc) from exc

            if sc is not None and sc >= 500:
                raise _RetryWithinModel(exc) from exc

            if sc in (404, 413, 422):
                raise _TryNextModel(exc) from exc

            if sc in (401, 403):
                raise LLMGatewayAuthError(
                    f"Authentication failed for {model}: {msg}"
                ) from exc

            if sc == 400:
                if any(m in msg_lower for m in JSON_MODE_ERROR_MARKERS):
                    raise _JsonModeNotSupported(exc) from exc
                raise LLMGatewayConfigError(
                    f"Bad request to {model}: {msg}"
                ) from exc

        raise LLMGatewayError(
            f"Unexpected error calling {model}: {msg}"
        ) from exc
