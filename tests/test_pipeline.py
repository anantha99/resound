"""Smoke tests that exercise the pipeline without hitting any external APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from resound.config import BrandConfig
from resound.core.classifier import Classifier
from resound.core.feedback import FeedbackChannel
from resound.core.source import SourceAdapter
from resound.gateway import (
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayExhaustedError,
    LLMResponse,
)
from resound.memory import LLMCallRow, SqlMemory
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


def _fake_response(model: str = "fake/test") -> LLMResponse:
    return LLMResponse(
        content="{}",
        model_used=model,
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.0001,
        latency_ms=5.0,
        raw_response={},
        was_fallback=False,
        attempt_count=1,
    )


class FakeClassifier(Classifier):
    def __init__(
        self,
        fixed: Classification | None = None,
        raise_exc: Exception | None = None,
    ):
        self.fixed = fixed
        self.raise_exc = raise_exc
        self.calls = 0

    def classify(
        self, raw: RawSignal, brand_context: str
    ) -> tuple[Classification, LLMResponse]:
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        assert self.fixed is not None
        return self.fixed, _fake_response()


class _RotatingClassifier(Classifier):
    """Returns each result from `results` in order. Raises if the entry is an Exception."""

    def __init__(self, results: list):
        self.results = list(results)
        self.idx = 0

    def classify(self, raw: RawSignal, brand_context: str):
        result = self.results[self.idx]
        self.idx += 1
        if isinstance(result, Exception):
            raise result
        return result, _fake_response()


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


# ---- three-tier exception backstop + audit-write tests (subtask 9.5/9.7) ----


def _llm_call_rows(memory: SqlMemory) -> list[LLMCallRow]:
    with Session(memory.engine) as s:
        return list(s.execute(select(LLMCallRow)).scalars())


def test_pipeline_writes_llm_call_on_success(brand, memory):
    fixed = _classification(area="cs", sev=Severity.MEDIUM)
    classifier = FakeClassifier(fixed=fixed)
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s1")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    pipe.run_once()
    rows = _llm_call_rows(memory)
    assert len(rows) == 1
    assert rows[0].stage == "classify"
    assert rows[0].success is True
    assert rows[0].signal_id is not None


def test_pipeline_writes_llm_failure_on_exhausted_error(brand, memory):
    classifier = FakeClassifier(
        raise_exc=LLMGatewayExhaustedError("all retries spent", attempts=3)
    )
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s2")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    stats = pipe.run_once()
    rows = [r for r in _llm_call_rows(memory) if r.success is False]
    assert len(rows) == 1
    assert rows[0].error_class == "LLMGatewayExhaustedError"
    assert rows[0].attempt_count == 3
    assert stats.errors == 1
    assert stats.classified == 0


def test_pipeline_substitutes_stub_on_exhausted_error(brand, memory):
    classifier = FakeClassifier(
        raise_exc=LLMGatewayExhaustedError("retries spent", attempts=3)
    )
    feedback = CapturingFeedback()
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s3")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=feedback,
    )
    pipe.run_once()
    # Stub Classification → ignored_by_classifier → no feedback fired.
    assert len(feedback.routes) == 0
    # But signal/classification/route rows still exist (stub-as-data).
    with Session(memory.engine) as s:
        from resound.memory import ClassificationRow
        cls_count = s.query(ClassificationRow).count()
    assert cls_count == 1


def test_pipeline_propagates_config_error_as_fatal(brand, memory):
    classifier = FakeClassifier(raise_exc=LLMGatewayConfigError("bad models.yaml"))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s4")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    with pytest.raises(LLMGatewayConfigError):
        pipe.run_once()


def test_pipeline_propagates_auth_error_as_fatal(brand, memory):
    classifier = FakeClassifier(raise_exc=LLMGatewayAuthError("401"))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s5")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    with pytest.raises(LLMGatewayAuthError):
        pipe.run_once()


def test_pipeline_substitutes_stub_on_unexpected_exception_no_audit(brand, memory):
    classifier = FakeClassifier(raise_exc=KeyError("unexpected internal bug"))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s6")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    stats = pipe.run_once()
    assert stats.errors == 1
    # No audit row — broad except path doesn't write llm_calls.
    assert len(_llm_call_rows(memory)) == 0


def test_pipeline_stub_routes_as_ignored_by_classifier(brand, memory):
    classifier = FakeClassifier(raise_exc=LLMGatewayExhaustedError("x", attempts=1))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s7")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    stats = pipe.run_once()
    assert stats.ignored == 1
    assert stats.routed == 0


def test_pipeline_stats_classified_only_increments_on_success(brand, memory):
    fixed = _classification(area="cs", sev=Severity.MEDIUM)
    classifier = _RotatingClassifier(
        results=[fixed, LLMGatewayExhaustedError("x", attempts=2)]
    )
    sources = [FakeSource(brand.slug, {}, [_signal(sid="ok"), _signal(sid="bad")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    stats = pipe.run_once()
    assert stats.classified == 1  # only the successful one
    assert stats.errors == 1


def test_pipeline_one_failure_does_not_block_other_signals(brand, memory):
    fixed = _classification(area="cs", sev=Severity.MEDIUM)
    classifier = _RotatingClassifier(
        results=[LLMGatewayExhaustedError("x", attempts=1), fixed]
    )
    sources = [FakeSource(brand.slug, {}, [_signal(sid="bad-first"), _signal(sid="ok-after")])]
    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=CapturingFeedback(),
    )
    stats = pipe.run_once()
    assert stats.new == 2
    assert stats.classified == 1
    assert stats.errors == 1


# ---- end-to-end smoke test (subtask 9.7 PART 3) ----


def test_smoke_real_classifier_through_pipeline(brand, memory):
    """Real OpenRouterClassifier + FakeGateway + real Pipeline + real SqlMemory.

    Closest test analogue to ``resound poll-once`` — verifies llm_calls row
    populates with the correct schema fields after a real classifier walk.
    """
    from resound.classifiers import OpenRouterClassifier
    from tests.test_classifier import FakeGateway, _ok_response

    valid_json = (
        '{"is_about_brand": true, "area": "cs", "sentiment": "negative", '
        '"severity": "medium", "action_class": "sprint", "summary": "smoke", '
        '"confidence": 0.85}'
    )
    fake_gw = FakeGateway(response=_ok_response(valid_json, model="anthropic/claude-fake"))
    classifier = OpenRouterClassifier(fake_gw)
    feedback = CapturingFeedback()
    sources = [FakeSource(brand.slug, {}, [_signal(sid="smoke1")])]

    pipe = Pipeline(
        brand=brand,
        sources=sources,
        classifier=classifier,
        router=RulesRouter(brand.routing, brand.people),
        memory=memory,
        feedback=feedback,
    )
    stats = pipe.run_once()

    assert stats.classified == 1
    assert stats.routed == 1
    assert len(feedback.routes) == 1

    rows = _llm_call_rows(memory)
    assert len(rows) == 1
    row = rows[0]
    assert row.stage == "classify"
    assert row.success is True
    assert row.model == "anthropic/claude-fake"
    assert row.signal_id is not None
    assert row.tokens_in == 10
    assert row.was_fallback is False
    assert row.attempt_count == 1
    assert "is_about_brand" in (row.response_content or "")
