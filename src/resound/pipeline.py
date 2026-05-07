"""The pipeline. Wires Source → Classifier → Router → Memory → Feedback.

This is the only place that knows about all five layers. Everything else is
single-responsibility and substitutable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from resound.classifiers import build_classifier, make_fallback_classification
from resound.config import BrandConfig
from resound.core.classifier import Classifier
from resound.core.feedback import FeedbackChannel
from resound.core.memory import Memory
from resound.core.router import Router
from resound.core.source import SourceAdapter
from resound.feedback import FileFeedback
from resound.gateway import (
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayError,
)
from resound.memory import SqlMemory
from resound.prompts.classify import build_classify_prompt
from resound.routers import RulesRouter
from resound.sources import build_sources

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    polled: int = 0
    new: int = 0
    classified: int = 0
    routed: int = 0
    ignored: int = 0
    errors: int = 0


class Pipeline:
    """Run one ingest cycle for one brand."""

    def __init__(
        self,
        brand: BrandConfig,
        sources: list[SourceAdapter] | None = None,
        classifier: Classifier | None = None,
        router: Router | None = None,
        memory: Memory | None = None,
        feedback: FeedbackChannel | None = None,
    ):
        self.brand = brand
        self.sources = sources if sources is not None else build_sources(brand.slug, brand.sources)
        self.classifier = classifier or build_classifier(brand.slug)
        self.router = router or RulesRouter(brand.routing, brand.people)
        self.memory = memory or SqlMemory()
        self.feedback = feedback or FileFeedback(brand.slug)

    def run_once(self) -> PipelineStats:
        stats = PipelineStats()

        for source in self.sources:
            logger.info("Polling source: %s", source.name)
            try:
                signals = list(source.poll())
            except Exception:
                logger.exception("Source %s failed", source.name)
                stats.errors += 1
                continue

            for raw in signals:
                stats.polled += 1
                key = raw.dedupe_key()

                if self.memory.has_seen(key):
                    continue

                stats.new += 1
                signal_id = self.memory.record_signal(self.brand.slug, raw)

                # Pre-build the prompt: needed by both success-path
                # record_llm_call and failure-path record_llm_failure.
                prompt = build_classify_prompt(raw, self.brand.understanding)
                t0 = time.perf_counter()

                try:
                    classification, response = self.classifier.classify(
                        raw, self.brand.understanding
                    )
                    self.memory.record_llm_call(
                        brand_slug=self.brand.slug,
                        signal_id=signal_id,
                        stage="classify",
                        prompt=prompt,
                        response=response,
                        was_fallback=response.was_fallback,
                        attempt_count=response.attempt_count,
                    )
                    stats.classified += 1
                except (LLMGatewayConfigError, LLMGatewayAuthError):
                    # FATAL per design #14 — operator must fix config/credentials.
                    raise
                except LLMGatewayError as exc:
                    self.memory.record_llm_failure(
                        brand_slug=self.brand.slug,
                        signal_id=signal_id,
                        stage="classify",
                        prompt=prompt,
                        error=exc,
                        latency_ms=(time.perf_counter() - t0) * 1000.0,
                        attempt_count=getattr(exc, "attempts", 1),
                    )
                    classification = make_fallback_classification(
                        f"{type(exc).__name__}: {exc}"
                    )
                    stats.errors += 1
                except Exception as exc:
                    # Backstop for unforeseen bugs. No properly-formed
                    # LLMGatewayError to record, so no audit row written.
                    logger.exception("Unexpected classifier failure on signal %s", key)
                    classification = make_fallback_classification(
                        f"unexpected: {type(exc).__name__}"
                    )
                    stats.errors += 1

                cls_id = self.memory.record_classification(signal_id, classification)

                route = self.router.route(raw, classification)
                route_id = self.memory.record_route(signal_id, cls_id, route)

                if route.matched_rule == "ignored_by_classifier":
                    stats.ignored += 1
                    continue

                stats.routed += 1
                try:
                    self.feedback.notify(raw, classification, route, signal_id, route_id)
                except Exception:
                    logger.exception("Feedback channel failed for signal %s", key)
                    stats.errors += 1

        return stats
