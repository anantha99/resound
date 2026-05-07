"""Unit tests for OpenRouterClassifier with a FakeGateway.

Covers the classifier's contract per design #36, #39, #40:
  * happy path returns (Classification, LLMResponse)
  * passes JSON_MODE sentinel and stage="classify" to the gateway
  * parse failures return stub-as-data with the actual LLMResponse
  * gateway exceptions propagate (classifier does NOT catch them)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from resound.classifiers import OpenRouterClassifier, make_fallback_classification
from resound.gateway import (
    JSON_MODE,
    LLMGateway,
    LLMGatewayConfigError,
    LLMGatewayExhaustedError,
    LLMResponse,
)
from resound.models import ActionClass, Classification, RawSignal


class FakeGateway(LLMGateway):
    """Drop-in stub. Either returns a fixed LLMResponse or raises."""

    def __init__(
        self,
        response: LLMResponse | None = None,
        raise_exc: Exception | None = None,
    ):
        self.response = response
        self.raise_exc = raise_exc
        self.calls: list[tuple[str, str, dict | None]] = []

    def complete(
        self,
        stage: str,
        prompt: str,
        response_schema: dict | None = None,
    ) -> LLMResponse:
        self.calls.append((stage, prompt, response_schema))
        if self.raise_exc is not None:
            raise self.raise_exc
        assert self.response is not None  # tests must set one
        return self.response


def _ok_response(content: str, model: str = "fake/model") -> LLMResponse:
    return LLMResponse(
        content=content,
        model_used=model,
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.0001,
        latency_ms=5.0,
        raw_response={},
        was_fallback=False,
        attempt_count=1,
    )


def _signal() -> RawSignal:
    return RawSignal(
        source="reddit",
        external_id="t3_test",
        url=None,
        author_handle="someone",
        content="hello world",
        posted_at=datetime.now(tz=timezone.utc),
    )


# ---- happy path ----


def test_classify_happy_path_returns_tuple_with_classification_and_response():
    valid_json = (
        '{"is_about_brand": true, "area": "cs", "sentiment": "negative", '
        '"severity": "medium", "action_class": "sprint", "summary": "test", '
        '"confidence": 0.8}'
    )
    gw = FakeGateway(response=_ok_response(valid_json))
    classifier = OpenRouterClassifier(gw)
    result = classifier.classify(_signal(), "brand context")
    assert isinstance(result, tuple) and len(result) == 2
    classification, response = result
    assert isinstance(classification, Classification)
    assert classification.is_about_brand is True
    assert classification.area == "cs"
    assert response is gw.response


def test_classify_passes_json_mode_sentinel_to_gateway():
    gw = FakeGateway(response=_ok_response('{"is_about_brand": false, "area": "other", "sentiment": "neutral", "severity": "low", "action_class": "ignore", "summary": "x"}'))
    OpenRouterClassifier(gw).classify(_signal(), "ctx")
    assert len(gw.calls) == 1
    _, _, schema = gw.calls[0]
    assert schema is JSON_MODE


def test_classify_uses_classify_stage_name():
    gw = FakeGateway(response=_ok_response('{"is_about_brand": false, "area": "other", "sentiment": "neutral", "severity": "low", "action_class": "ignore", "summary": "x"}'))
    OpenRouterClassifier(gw).classify(_signal(), "ctx")
    stage, _, _ = gw.calls[0]
    assert stage == "classify"


# ---- parse failures (stub-as-data) ----


def test_classify_parse_no_json_returns_stub_with_response():
    gw = FakeGateway(response=_ok_response("there is no json here at all"))
    classification, response = OpenRouterClassifier(gw).classify(_signal(), "ctx")
    assert classification.is_about_brand is False
    assert classification.action_class == ActionClass.IGNORE
    assert "no_json_in_response" in (classification.reasoning or "")
    assert response is gw.response  # successful gateway call preserved


def test_classify_parse_bad_json_returns_stub():
    # Has `{...}` so the extraction regex matches, but isn't valid JSON.
    gw = FakeGateway(response=_ok_response("{not valid: json,,,}"))
    classification, _ = OpenRouterClassifier(gw).classify(_signal(), "ctx")
    assert "json_decode_error" in (classification.reasoning or "")


def test_classify_parse_pydantic_validation_returns_stub():
    # Valid JSON but invalid sentiment enum value.
    bad = '{"is_about_brand": true, "area": "cs", "sentiment": "WIZARDRY"}'
    gw = FakeGateway(response=_ok_response(bad))
    classification, _ = OpenRouterClassifier(gw).classify(_signal(), "ctx")
    assert "validation_error" in (classification.reasoning or "")


# ---- gateway exception propagation ----


def test_classify_propagates_gateway_exhausted_error():
    gw = FakeGateway(raise_exc=LLMGatewayExhaustedError("all retries spent", attempts=3))
    with pytest.raises(LLMGatewayExhaustedError):
        OpenRouterClassifier(gw).classify(_signal(), "ctx")


def test_classify_propagates_gateway_config_error():
    gw = FakeGateway(raise_exc=LLMGatewayConfigError("bad models.yaml"))
    with pytest.raises(LLMGatewayConfigError):
        OpenRouterClassifier(gw).classify(_signal(), "ctx")


# ---- make_fallback_classification shape ----


def test_make_fallback_classification_has_correct_defaults():
    cls = make_fallback_classification("test reason")
    assert cls.is_about_brand is False
    assert cls.area == "other"
    assert cls.action_class == ActionClass.IGNORE
    assert cls.confidence == 0.0
    assert "test reason" in cls.summary
    assert cls.reasoning == "test reason"
