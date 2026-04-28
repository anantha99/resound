"""Claude-backed classifier. Calls Anthropic's API with the v1 prompt."""

from __future__ import annotations

import json
import logging
import re

from anthropic import Anthropic

from resound.config import env, require_env
from resound.core.classifier import Classifier
from resound.models import (
    ActionClass,
    Classification,
    RawSignal,
    Sentiment,
    Severity,
)
from resound.prompts import build_classify_messages

logger = logging.getLogger(__name__)


class ClaudeClassifier(Classifier):
    """Classifier using Anthropic's Claude. Configurable model via env."""

    def __init__(self, model: str | None = None, max_tokens: int = 1024):
        require_env("ANTHROPIC_API_KEY")
        self.client = Anthropic()
        self.model = model or env("RESOUND_CLASSIFIER_MODEL", "claude-sonnet-4-6")
        self.max_tokens = max_tokens

    def classify(self, raw: RawSignal, brand_context: str) -> Classification:
        system, messages = build_classify_messages(raw, brand_context)

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=messages,
            )
        except Exception as exc:
            logger.exception("Claude API call failed")
            return self._fallback(raw, reason=f"api_error: {exc}")

        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        return self._parse(text, raw)

    # --- helpers ---

    def _parse(self, text: str, raw: RawSignal) -> Classification:
        # Strip markdown code fences if Claude added them despite instructions.
        text = text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            logger.warning("No JSON object found in classifier response")
            return self._fallback(raw, reason="no_json_in_response")

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning(f"JSON decode failed: {exc}")
            return self._fallback(raw, reason="json_decode_error")

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
            return self._fallback(raw, reason=f"validation_error: {exc}")

    @staticmethod
    def _fallback(raw: RawSignal, reason: str) -> Classification:
        return Classification(
            is_about_brand=False,
            area="other",
            sentiment=Sentiment.NEUTRAL,
            severity=Severity.LOW,
            action_class=ActionClass.IGNORE,
            summary=f"[classifier fallback: {reason}]",
            confidence=0.0,
            reasoning=reason,
        )
