# Creates ONLY subtask 9.7 (the test-suite subtask) which was skipped by
# apply-task9-grilling.ps1 because its --details payload (~17 KB, 215 embedded
# double-quotes, 441 newlines) exceeds the practical PowerShell -> node.exe
# native-command argument-passing budget on Windows.
#
# Strategy:
#   1. Call `task-master add-subtask` with a small UNIQUE PLACEHOLDER as
#      --details (CLI happily accepts ~30-char payloads).
#   2. Read tasks.json as raw text, replace the JSON-encoded placeholder
#      with the JSON-encoded full details body, write back UTF-8 (no BOM).
#      Targeted text substitution preserves the existing 2-space indent
#      and field ordering -- no whole-file reformat.
#   3. Call `task-master generate` to refresh the per-task .md file.
#
# RUN THIS FROM A SEPARATE TERMINAL (outside an active Claude Code session).
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File .taskmaster/scripts/apply-task9-7.ps1
#
# NOT idempotent: the pre-flight check refuses to run if a subtask with
# matching title already exists under task 9.
#
# Authoritative spec: docs/design_decisions.md (Task 9 section, decision #43).

$ErrorActionPreference = 'Stop'

$tasksPath  = '.taskmaster/tasks/tasks.json'
$parentId   = 9
$placeholder = '__APPLY_TASK9_7_PATCH_PLACEHOLDER_DO_NOT_REMOVE__'

$title_9_7 = 'Tests: new tests/test_classifier.py + extend tests/test_pipeline.py + smoke test'

$desc_9_7 = 'Two-file test split. New tests/test_classifier.py (~8 cases with FakeGateway). Extended tests/test_pipeline.py (~9 new cases with updated FakeClassifier). One end-to-end smoke test wiring real OpenRouterClassifier + FakeGateway + real Pipeline + real SqlMemory.'

$details_9_7 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #43).

PART 1 -- New file: tests/test_classifier.py

Approximate structure (~120 lines, ~8 tests):

"""Unit tests for OpenRouterClassifier with a FakeGateway.

Covers the classifier's contract:
  * happy path returns (Classification, LLMResponse)
  * passes JSON_MODE sentinel and stage="classify" to gateway
  * parse failures return stub-as-data with the actual LLMResponse
  * gateway exceptions propagate (classifier does NOT catch them)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from resound.classifiers import (
    OpenRouterClassifier,
    make_fallback_classification,
)
from resound.gateway import (
    JSON_MODE,
    LLMGateway,
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayExhaustedError,
    LLMResponse,
)
from resound.models import (
    ActionClass,
    Classification,
    RawSignal,
    Sentiment,
    Severity,
)


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
    gw = FakeGateway(response=_ok_response('{"is_about_brand": false}'))
    OpenRouterClassifier(gw).classify(_signal(), "ctx")
    assert len(gw.calls) == 1
    stage, prompt, schema = gw.calls[0]
    assert schema is JSON_MODE


def test_classify_uses_classify_stage_name():
    gw = FakeGateway(response=_ok_response('{"is_about_brand": false}'))
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
    gw = FakeGateway(response=_ok_response('{"truncated": "json'))
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


PART 2 -- Update tests/test_pipeline.py

Update the existing FakeClassifier (lines 40-47) to match the new ABC return type:

class FakeClassifier(Classifier):
    def __init__(
        self,
        fixed: Classification | None = None,
        raise_exc: Exception | None = None,
    ):
        self.fixed = fixed
        self.raise_exc = raise_exc
        self.calls = 0

    def classify(self, raw, brand_context) -> tuple[Classification, LLMResponse]:
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.fixed, _fake_response()


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

The existing tests (test_pipeline_end_to_end, test_pipeline_dedupes_on_second_run) should still pass with this updated FakeClassifier -- they construct it with fixed=Classification(...) which now matches the new __init__ signature.

ADD these new tests to tests/test_pipeline.py:

from resound.gateway import (
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayExhaustedError,
    LLMGatewayParseError,
)


def test_pipeline_writes_llm_call_on_success(brand, memory):
    fixed = _classification(area="cs", sev=Severity.MEDIUM)
    classifier = FakeClassifier(fixed=fixed)
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s1")])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    pipe.run_once()
    # Inspect llm_calls table directly.
    rows = list(memory.engine.connect().execute(
        "SELECT * FROM llm_calls"
    ))
    assert len(rows) == 1
    assert rows[0].stage == "classify"
    assert rows[0].success is True
    assert rows[0].signal_id is not None


def test_pipeline_writes_llm_failure_on_exhausted_error(brand, memory):
    classifier = FakeClassifier(
        raise_exc=LLMGatewayExhaustedError("all retries spent", attempts=3)
    )
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s2")])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    stats = pipe.run_once()
    rows = list(memory.engine.connect().execute(
        "SELECT * FROM llm_calls WHERE success = 0"
    ))
    assert len(rows) == 1
    assert rows[0].error_class == "LLMGatewayExhaustedError"
    assert stats.errors == 1
    assert stats.classified == 0


def test_pipeline_substitutes_stub_on_exhausted_error(brand, memory):
    classifier = FakeClassifier(
        raise_exc=LLMGatewayExhaustedError("retries spent", attempts=3)
    )
    feedback = CapturingFeedback()
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s3")])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=feedback)
    pipe.run_once()
    # Stub Classification -> ignored_by_classifier -> no feedback fired.
    assert len(feedback.routes) == 0
    # But signal/classification/route rows still exist (stub-as-data).
    cls_rows = list(memory.engine.connect().execute(
        "SELECT * FROM classifications"
    ))
    assert len(cls_rows) == 1


def test_pipeline_propagates_config_error_as_fatal(brand, memory):
    classifier = FakeClassifier(raise_exc=LLMGatewayConfigError("bad models.yaml"))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s4")])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    with pytest.raises(LLMGatewayConfigError):
        pipe.run_once()


def test_pipeline_propagates_auth_error_as_fatal(brand, memory):
    classifier = FakeClassifier(raise_exc=LLMGatewayAuthError("401"))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s5")])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    with pytest.raises(LLMGatewayAuthError):
        pipe.run_once()


def test_pipeline_substitutes_stub_on_unexpected_exception_no_audit(brand, memory):
    classifier = FakeClassifier(raise_exc=KeyError("unexpected internal bug"))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s6")])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    stats = pipe.run_once()
    assert stats.errors == 1
    # No audit row -- broad except path doesn't write llm_calls.
    rows = list(memory.engine.connect().execute("SELECT * FROM llm_calls"))
    assert len(rows) == 0


def test_pipeline_stub_routes_as_ignored_by_classifier(brand, memory):
    classifier = FakeClassifier(raise_exc=LLMGatewayExhaustedError("x", attempts=1))
    sources = [FakeSource(brand.slug, {}, [_signal(sid="s7")])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    stats = pipe.run_once()
    assert stats.ignored == 1
    assert stats.routed == 0


def test_pipeline_stats_classified_only_increments_on_success(brand, memory):
    # One signal succeeds, one fails.
    fixed = _classification(area="cs", sev=Severity.MEDIUM)
    classifier = _RotatingClassifier(  # fixture below
        results=[fixed, LLMGatewayExhaustedError("x", attempts=2)]
    )
    sources = [FakeSource(brand.slug, {}, [
        _signal(sid="ok"), _signal(sid="bad")
    ])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    stats = pipe.run_once()
    assert stats.classified == 1  # only the successful one
    assert stats.errors == 1


def test_pipeline_one_failure_does_not_block_other_signals(brand, memory):
    # Same as above; assert isolation.
    fixed = _classification(area="cs", sev=Severity.MEDIUM)
    classifier = _RotatingClassifier(
        results=[LLMGatewayExhaustedError("x", attempts=1), fixed]
    )
    sources = [FakeSource(brand.slug, {}, [
        _signal(sid="bad-first"), _signal(sid="ok-after")
    ])]
    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=CapturingFeedback())
    stats = pipe.run_once()
    assert stats.new == 2
    assert stats.classified == 1
    assert stats.errors == 1


# Helper for tests that need different results across calls:
class _RotatingClassifier(Classifier):
    def __init__(self, results):
        self.results = list(results)
        self.idx = 0
    def classify(self, raw, brand_context):
        result = self.results[self.idx]
        self.idx += 1
        if isinstance(result, Exception):
            raise result
        return result, _fake_response()


PART 3 -- Smoke test in tests/test_pipeline.py

Add this end-to-end smoke test that wires real OpenRouterClassifier through a real Pipeline against a real SqlMemory, with only the gateway being a fake:

def test_smoke_real_classifier_through_pipeline(brand, memory):
    """End-to-end: real OpenRouterClassifier + FakeGateway + real Pipeline +
    real SqlMemory. Verifies llm_calls row populates with correct schema fields
    after a real classifier walk. Closest test analogue to `resound poll-once`."""
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

    pipe = Pipeline(brand=brand, sources=sources, classifier=classifier,
                    router=RulesRouter(brand.routing, brand.people),
                    memory=memory, feedback=feedback)
    stats = pipe.run_once()

    # Pipeline went through to feedback (route fired).
    assert stats.classified == 1
    assert stats.routed == 1
    assert len(feedback.routes) == 1

    # llm_calls row populated with expected schema fields.
    rows = list(memory.engine.connect().execute("SELECT * FROM llm_calls"))
    assert len(rows) == 1
    row = rows[0]
    assert row.stage == "classify"
    assert row.success is True
    assert row.model == "anthropic/claude-fake"
    assert row.signal_id is not None
    assert row.tokens_in > 0
    assert row.was_fallback is False
    assert row.attempt_count == 1
    # Verify the response_content was preserved.
    assert "is_about_brand" in (row.response_content or "")

CRITICAL constraints:

1. Tests for the classifier (PART 1) MUST use FakeGateway, not mock the openai SDK directly. The point of #39 is that gateway is the seam -- tests should mock at that seam.

2. Tests for the Pipeline (PART 2) MUST NOT import or instantiate OpenRouterGateway. They use FakeClassifier injection (existing pattern). Pipeline tests are about orchestration and audit-write behavior, not about gateway internals.

3. The smoke test (PART 3) is the ONE test that wires real classifier + Pipeline + SqlMemory together. It uses FakeGateway because we don't want network calls in CI. This is the closest test to a real `resound poll-once` invocation.

4. SqlMemory's engine.connect().execute() pattern in the assertions assumes raw SQL is acceptable for tests. If the existing test_llm_calls.py (from Task 3) uses a different query API (e.g. session-based), MIRROR that pattern for consistency. The exact query API can be adapted.

5. The _RotatingClassifier helper is for the multi-signal tests where one succeeds and one fails. Don't over-design -- just a list of results, advance an index per call.

6. Tests must run on Windows (the user's platform per environment) -- no POSIX-only path tricks.

7. Existing tests in tests/test_pipeline.py (test_pipeline_end_to_end, test_pipeline_dedupes_on_second_run) MUST continue to pass with only the FakeClassifier signature update. Don't rewrite their bodies.

Acceptance criteria:
- tests/test_classifier.py exists with ~9 test cases (8 classifier + 1 fallback shape).
- tests/test_pipeline.py extended with ~9 new test cases for the three-tier exception handling and audit-write behavior.
- One smoke test wires real OpenRouterClassifier + FakeGateway + real Pipeline + real SqlMemory and asserts llm_calls row population.
- All existing tests in tests/test_pipeline.py continue to pass after the FakeClassifier update.
- Total new test count: ~17.
- pytest run completes without errors. Total runtime under 10 seconds.
- No test depends on network, OpenRouter API, or OPENROUTER_API_KEY being set.
'@

# ----------------------------------------------------------------------------
# Pre-flight checks
# ----------------------------------------------------------------------------

if (-not (Test-Path $tasksPath)) {
    throw "tasks.json not found at $tasksPath. Run from project root."
}

$json = Get-Content -Raw -Encoding UTF8 $tasksPath | ConvertFrom-Json
$task9 = $json.master.tasks | Where-Object { $_.id -eq $parentId }
if (-not $task9) {
    throw "Task $parentId not found in $tasksPath."
}

$existing = $task9.subtasks | Where-Object { $_.title -eq $title_9_7 }
if ($existing) {
    Write-Host "Subtask 9.$($existing.id) with this title already exists. Aborting (not idempotent)." -ForegroundColor Yellow
    exit 0
}

# ----------------------------------------------------------------------------
# Step 1: create the subtask via task-master with a small placeholder details
# ----------------------------------------------------------------------------

Write-Host "==> Step 1/3: creating subtask 9.7 via task-master add-subtask (placeholder details)..." -ForegroundColor Cyan
task-master add-subtask `
    --parent=$parentId `
    --title=$title_9_7 `
    --description=$desc_9_7 `
    --details=$placeholder

if ($LASTEXITCODE -ne 0) {
    throw "task-master add-subtask failed (exit $LASTEXITCODE). The placeholder approach should never fail on length grounds -- investigate."
}

# ----------------------------------------------------------------------------
# Step 2: patch the full details into tasks.json via targeted text replace
# ----------------------------------------------------------------------------

Write-Host "==> Step 2/3: patching full details into tasks.json (targeted text replace)..." -ForegroundColor Cyan

$raw = Get-Content -Raw -Encoding UTF8 $tasksPath

# JSON-encode both the placeholder (for searching) and the full details (for replacement).
# ConvertTo-Json on a single string returns "<escaped-quoted-string>", which is exactly
# what appears in tasks.json on the right-hand side of "details": ...
$placeholderEncoded = ($placeholder | ConvertTo-Json)
$detailsEncoded     = ($details_9_7 | ConvertTo-Json)

# Defensive: the placeholder must appear exactly once in the file.
$occurrences = ([regex]::Matches($raw, [regex]::Escape($placeholderEncoded))).Count
if ($occurrences -ne 1) {
    throw "Placeholder appeared $occurrences times in tasks.json (expected exactly 1). Aborting before write to avoid corruption."
}

# -replace treats $ in the replacement string as a backreference token; double them out
# to be safe even though the current details body has no '$' chars.
$detailsEncodedSafe = $detailsEncoded.Replace('$', '$$')

$updated = $raw -replace [regex]::Escape($placeholderEncoded), $detailsEncodedSafe

# Write back as UTF-8 NO BOM (matches what task-master writes).
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText((Resolve-Path $tasksPath).Path, $updated, $utf8NoBom)

# ----------------------------------------------------------------------------
# Step 3: regenerate per-task .md file so it picks up the new subtask + details
# ----------------------------------------------------------------------------

Write-Host "==> Step 3/3: regenerating task .md files via task-master generate..." -ForegroundColor Cyan
task-master generate
if ($LASTEXITCODE -ne 0) {
    Write-Host "task-master generate exited $LASTEXITCODE -- tasks.json is correct, but the .md file may be stale. Re-run 'task-master generate' manually." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Verify with: task-master show 9" -ForegroundColor Green
Write-Host "Authoritative design spec: docs/design_decisions.md (decision #43)" -ForegroundColor Gray
