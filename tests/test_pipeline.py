"""Smoke tests that exercise the pipeline without hitting any external APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pytest

from resound.config import BrandConfig
from resound.core.classifier import Classifier
from resound.core.feedback import FeedbackChannel
from resound.core.source import SourceAdapter
from resound.memory import SqlMemory
from resound.models import (
    ActionClass,
    Classification,
    RawSignal,
    Route,
    Sentiment,
    Severity,
)
from resound.pipeline import Pipeline
from resound.routers import RulesRouter


# ---- fakes ----

class FakeSource(SourceAdapter):
    name = "fake"

    def __init__(self, brand_slug: str, params: dict, signals: list[RawSignal]):
        super().__init__(brand_slug, params)
        self._signals = signals

    def poll(self) -> Iterable[RawSignal]:
        return list(self._signals)


class FakeClassifier(Classifier):
    def __init__(self, fixed: Classification):
        self.fixed = fixed
        self.calls = 0

    def classify(self, raw: RawSignal, brand_context: str) -> Classification:
        self.calls += 1
        return self.fixed


class CapturingFeedback(FeedbackChannel):
    def __init__(self):
        self.routes: list = []

    def notify(self, signal, classification, route, signal_id, route_id):
        self.routes.append((signal_id, route_id, route.owner_id, classification.summary))


# ---- fixtures ----

@pytest.fixture
def memory(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    return SqlMemory()


@pytest.fixture
def routing_config():
    return {
        "default_route": "#triage",
        "rules": [
            {"name": "critical_pr", "when": {"severity": "critical"}, "route_to": "#exec-pr"},
            {"name": "billing_high", "when": {"area": "billing", "severity": ">=high"}, "route_to": "@billing"},
            {"name": "low_confidence", "when": {"confidence": "<0.5"}, "route_to": "#review"},
        ],
    }


@pytest.fixture
def people_config():
    return {
        "people": {"@billing": {"name": "B", "slack": "@U_BILLING"}},
        "channels": {"#exec-pr": {"slack_channel": "#pr"}, "#triage": {"slack_channel": "#tri"}},
    }


@pytest.fixture
def brand(routing_config, people_config):
    return BrandConfig(
        slug="testbrand",
        brand={"name": "Test Brand"},
        sources={},
        routing=routing_config,
        people=people_config,
        understanding="A test brand.",
    )


def _signal(content="hello world", sid="x1") -> RawSignal:
    return RawSignal(
        source="fake",
        external_id=sid,
        url=None,
        author_handle="someone",
        content=content,
        posted_at=datetime.now(tz=timezone.utc),
    )


def _classification(area="cs", sev=Severity.MEDIUM, action=ActionClass.SPRINT, conf=0.8, about=True):
    return Classification(
        is_about_brand=about,
        area=area,
        sentiment=Sentiment.NEUTRAL,
        severity=sev,
        action_class=action,
        summary="test",
        confidence=conf,
    )


# ---- tests ----

def test_memory_dedup(memory):
    raw = _signal()
    sid = memory.record_signal("testbrand", raw)
    assert isinstance(sid, int)
    assert memory.has_seen(raw.dedupe_key())
    assert not memory.has_seen("nope::nothing")


def test_router_critical_routes_to_exec(routing_config, people_config):
    router = RulesRouter(routing_config, people_config)
    raw = _signal()
    cls = _classification(sev=Severity.CRITICAL)
    route = router.route(raw, cls)
    assert route.owner_id == "#exec-pr"
    assert route.matched_rule == "critical_pr"


def test_router_billing_high_match(routing_config, people_config):
    router = RulesRouter(routing_config, people_config)
    cls = _classification(area="billing", sev=Severity.HIGH)
    route = router.route(_signal(), cls)
    assert route.owner_id == "@billing"
    assert route.destination == "@U_BILLING"


def test_router_low_confidence_to_review(routing_config, people_config):
    router = RulesRouter(routing_config, people_config)
    cls = _classification(conf=0.3)
    route = router.route(_signal(), cls)
    assert route.owner_id == "#review"


def test_router_default_when_no_rule_matches(routing_config, people_config):
    router = RulesRouter(routing_config, people_config)
    cls = _classification(area="other", sev=Severity.LOW, conf=0.9)
    route = router.route(_signal(), cls)
    assert route.matched_rule == "default"
    assert route.owner_id == "#triage"


def test_router_ignores_off_brand(routing_config, people_config):
    router = RulesRouter(routing_config, people_config)
    cls = _classification(about=False, action=ActionClass.IGNORE)
    route = router.route(_signal(), cls)
    assert route.matched_rule == "ignored_by_classifier"


def test_pipeline_end_to_end(brand, memory):
    fixed_cls = _classification(area="billing", sev=Severity.HIGH, conf=0.9)
    classifier = FakeClassifier(fixed_cls)
    feedback = CapturingFeedback()
    sources = [FakeSource(brand.slug, {}, [_signal(sid="a"), _signal(sid="b")])]
    router = RulesRouter(brand.routing, brand.people)

    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=router,
        memory=memory,
        feedback=feedback,
    )
    stats = pipe.run_once()

    assert stats.polled == 2
    assert stats.new == 2
    assert stats.classified == 2
    assert stats.routed == 2
    assert classifier.calls == 2
    assert len(feedback.routes) == 2
    # both should hit the billing rule
    assert all(r[2] == "@billing" for r in feedback.routes)


def test_pipeline_dedupes_on_second_run(brand, memory):
    fixed_cls = _classification()
    classifier = FakeClassifier(fixed_cls)
    feedback = CapturingFeedback()
    sources = [FakeSource(brand.slug, {}, [_signal(sid="z")])]

    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=feedback,
    )
    s1 = pipe.run_once()
    s2 = pipe.run_once()
    assert s1.new == 1
    assert s2.new == 0
    assert classifier.calls == 1  # second run hit dedup
