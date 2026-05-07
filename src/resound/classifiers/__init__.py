"""Classifier implementations."""

from __future__ import annotations

from resound.classifiers.openrouter import OpenRouterClassifier
from resound.core.classifier import Classifier
from resound.gateway import build_gateway
from resound.models import ActionClass, Classification, Sentiment, Severity

__all__ = [
    "OpenRouterClassifier",
    "build_classifier",
    "make_fallback_classification",
]


def build_classifier(brand_slug: str) -> Classifier:
    """Build the default classifier for a brand.

    Loads brand-specific ``models.yaml`` overrides via the gateway factory
    (per design #16). OpenRouter is the only LLM path.
    """
    return OpenRouterClassifier(build_gateway(brand_slug))


def make_fallback_classification(reason: str) -> Classification:
    """Build a stub Classification used on classifier-parse and gateway-error paths.

    Per design #40, both ``OpenRouterClassifier._parse`` (parse failures) and
    ``Pipeline.run_once`` (``LLMGatewayError`` and broad ``Exception`` paths)
    emit this stub so a failed signal still flows through router → memory →
    feedback as ``IGNORE`` and ends up with rows in every table.
    """
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
