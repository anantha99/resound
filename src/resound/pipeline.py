"""The pipeline. Wires Source → Classifier → Router → Memory → Feedback.

This is the only place that knows about all five layers. Everything else is
single-responsibility and substitutable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from resound.classifiers import ClaudeClassifier
from resound.config import BrandConfig
from resound.core.classifier import Classifier
from resound.core.feedback import FeedbackChannel
from resound.core.memory import Memory
from resound.core.router import Router
from resound.core.source import SourceAdapter
from resound.feedback import FileFeedback
from resound.memory import SqlMemory
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
        self.classifier = classifier or ClaudeClassifier()
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

                try:
                    classification = self.classifier.classify(raw, self.brand.understanding)
                except Exception:
                    logger.exception("Classifier failed on signal %s", key)
                    stats.errors += 1
                    continue
                stats.classified += 1
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
