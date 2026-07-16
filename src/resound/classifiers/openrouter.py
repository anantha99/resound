"""OpenRouter-backed classifier. Thin wrapper over the LLM gateway.

Classification logic is split:
  * Prompt assembly: ``resound.prompts.classify.build_classify_prompt``
  * Model selection + retry/fallback: ``resound.gateway.OpenRouterGateway``
  * JSON parse + Pydantic validation: ``parse_classification_response_strict``
  * Audit-trail write: ``Pipeline.run_once`` (caller's responsibility)
  * Stub-substitution on gateway errors: ``Pipeline.run_once``
  * Legacy stub parser: ``parse_classification_response``
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from resound.core.classifier import Classifier
from resound.gateway import JSON_MODE, LLMGateway, LLMGatewayParseError, LLMResponse
from resound.models import (
    Classification,
    RawSignal,
)
from resound.prompts.classify import build_classify_prompt

logger = logging.getLogger(__name__)


class OpenRouterClassifier(Classifier):
    """Classifier that delegates to an LLMGateway for the classify stage."""

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    def classify(
        self, raw: RawSignal, brand_context: str
    ) -> tuple[Classification, LLMResponse]:
        """Run the classify stage. Returns (classification, llm_response).

        The pipeline uses the LLMResponse to write the llm_calls audit row.
        This legacy classifier preserves normal production behavior: malformed
        content becomes an IGNORE fallback classification. Demo population uses
        strict validation through ``SignalTriageAgent`` instead.
        """
        prompt = build_classify_prompt(raw, brand_context)
        response = self.gateway.complete(
            stage="classify",
            prompt=prompt,
            response_schema=JSON_MODE,
        )
        classification = parse_classification_response(response.content)
        return classification, response

    @staticmethod
    def _parse(text: str) -> Classification:
        return parse_classification_response(text)


def parse_classification_response(text: str) -> Classification:
    """Extract a Classification from gateway-returned content.

    Returns a stub Classification (via make_fallback_classification) on any
    parse failure. Does not raise. The caller still records a successful
    llm_calls row; only the downstream parse failed.
    """
    from resound.classifiers import make_fallback_classification

    try:
        return parse_classification_response_strict(text)
    except LLMGatewayParseError as exc:
        logger.warning("Classification parse failed: %s", exc)
        return make_fallback_classification(str(exc))


def parse_classification_response_strict(text: str) -> Classification:
    """Parse and validate classifier output, raising on malformed content."""
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise LLMGatewayParseError("no_json_in_response", raw_text=text)
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise LLMGatewayParseError(
            f"json_decode_error: {exc}", raw_text=text
        ) from exc
    try:
        return Classification.model_validate(data)
    except ValidationError as exc:
        raise LLMGatewayParseError(
            f"validation_error: {exc}", raw_text=text
        ) from exc
