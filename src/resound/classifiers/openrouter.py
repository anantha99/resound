"""OpenRouter-backed classifier. Thin wrapper over the LLM gateway.

Classification logic is split:
  * Prompt assembly: ``resound.prompts.classify.build_classify_prompt``
  * Model selection + retry/fallback: ``resound.gateway.OpenRouterGateway``
  * JSON parse + Pydantic validation: ``_parse`` (this module)
  * Audit-trail write: ``Pipeline.run_once`` (caller's responsibility)
  * Stub-substitution on gateway errors: ``Pipeline.run_once``
  * Stub-substitution on parse failures: ``_parse`` (returns stub-as-data)
"""

from __future__ import annotations

import json
import logging
import re

from resound.core.classifier import Classifier
from resound.gateway import JSON_MODE, LLMGateway, LLMResponse
from resound.models import (
    ActionClass,
    Classification,
    RawSignal,
    Sentiment,
    Severity,
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
        Gateway exceptions (LLMGatewayError and subclasses) propagate up to
        the caller — this method does NOT catch them. Parse failures
        DO NOT raise; they return a stub Classification with the reason
        in summary/reasoning, paired with the actual LLMResponse so the
        caller can record a successful audit row with the unparseable
        content preserved.
        """
        prompt = build_classify_prompt(raw, brand_context)
        response = self.gateway.complete(
            stage="classify",
            prompt=prompt,
            response_schema=JSON_MODE,
        )
        classification = self._parse(response.content)
        return classification, response

    @staticmethod
    def _parse(text: str) -> Classification:
        """Extract a Classification from gateway-returned content.

        Returns a stub Classification (via make_fallback_classification) on
        any parse failure. Does not raise. The caller still records a
        SUCCESSFUL llm_calls row — the gateway call DID succeed; only the
        downstream parse failed. The unparseable content is preserved in
        llm_calls.response_content for forensics.
        """
        from resound.classifiers import make_fallback_classification

        text = text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("No JSON object found in classifier response")
            return make_fallback_classification("no_json_in_response")

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning(f"JSON decode failed: {exc}")
            return make_fallback_classification(f"json_decode_error: {exc}")

        try:
            return Classification(
                is_about_brand=bool(data.get("is_about_brand", False)),
                area=str(data.get("area", "other")),
                subarea=data.get("subarea"),
                sentiment=Sentiment(data.get("sentiment", "neutral")),
                severity=Severity(data.get("severity", "low")),
                action_class=ActionClass(data.get("action_class", "ignore")),
                summary=str(data.get("summary", ""))[:280],
                root_cause_hypothesis=data.get("root_cause_hypothesis"),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning"),
            )
        except (ValueError, KeyError) as exc:
            logger.warning(f"Classification validation failed: {exc}")
            return make_fallback_classification(f"validation_error: {exc}")
