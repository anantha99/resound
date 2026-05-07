# Creates the 7 subtasks for Task 9 (refactor classifiers to use gateway) with
# locked design decisions from the 2026-05-07 grilling session baked into
# --details at creation time. Uses add-subtask (a pure structural CLI op, no
# AI subprocess) to avoid the spawn-claude problem we hit with update-subtask.
#
# RUN THIS FROM A SEPARATE TERMINAL (outside an active Claude Code session)
# in case any task-master CLI path still spawns child claude processes.
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File .taskmaster/scripts/apply-task9-grilling.ps1
#
# NOT idempotent: re-running creates duplicate subtasks. Run exactly once.
# Verify with: task-master show 9
#
# Note: Task 9 is the wiring step that activates the infrastructure shipped
# in Tasks 1-3. Tasks 4-8 remain skipped per the user's reduced-demo plan;
# Task 9 ships with one gateway consumer (the classifier) and explicit
# acknowledgment that future stages will need their own factory wiring.
#
# Authoritative spec: docs/design_decisions.md (Task 9 section, decisions #35-#44).

$ErrorActionPreference = 'Stop'

# ----------------------------------------------------------------------------
# Subtask 9.1 — Delete ClaudeClassifier and clean up env vars + dependencies
# ----------------------------------------------------------------------------

$title_9_1 = 'Delete ClaudeClassifier and clean up env vars + dependencies'

$desc_9_1 = 'Hard-remove the direct-Anthropic classifier path. OpenRouter becomes the only LLM path. Cleans up .env.example, README, pyproject, and the classifier factory.'

$details_9_1 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #35, #41).

DELETIONS:

1. File: src/resound/classifiers/claude.py
   Delete the whole file.

2. File: pyproject.toml
   Remove the "anthropic" entry from dependencies. Keep openai, pydantic, etc.

3. File: .env.example
   Delete the following lines / blocks:
   - Line 1-2: # Classifier provider comment + RESOUND_CLASSIFIER_PROVIDER=openrouter
   - Line 8-9: # Anthropic comment + ANTHROPIC_API_KEY=
   - Lines 27-31: the entire DEPRECATED RESOUND_CLASSIFIER_MODEL block (was already commented-out per design #25)
   Keep the explanatory comment at lines 23-25 about models.yaml — it remains accurate.

4. File: src/resound/classifiers/openrouter.py
   In __init__, remove the line that reads env("RESOUND_CLASSIFIER_MODEL", ...). The classifier no longer reads any env var directly; model resolution flows through the gateway via models.yaml (per #16). Note: the full constructor and classify() body get rewritten in subtask 9.4 — this subtask only verifies the env var read is removed in passing.

5. File: src/resound/classifiers/__init__.py
   Replace the existing build_classifier() factory body with the simplified form. The provider toggle goes away. Exact replacement happens in subtask 9.5; this subtask removes the ClaudeClassifier import only:

   - Remove: from resound.classifiers.claude import ClaudeClassifier
   - Remove: "ClaudeClassifier" from __all__

6. File: README.md — line-by-line cleanup:
   - Line 5: change "Claude classification" to "OpenRouter classification"
   - Line 45-46 paragraph: rewrite to remove RESOUND_CLASSIFIER_MODEL reference; point at config/models.yaml and brands/<slug>/models.yaml as the model selection mechanism
   - Line 49 paragraph: delete entirely (the "To use the Anthropic SDK directly..." block)
   - Line 74: change "classify each new post via Claude" to "classify each new post via OpenRouter"
   - Line 121: change "Claude classifier" to "OpenRouter-backed classifier"

CRITICAL constraints:

1. Do NOT introduce a compat shim for any of the three deleted env vars. Pre-launch product, no real users to migrate (per #41).

2. Do NOT add a startup deprecation warning. Same reasoning — ceremony for a non-existent migration audience.

3. After this subtask completes, the only LLM provider env var that remains in the codebase is OPENROUTER_API_KEY. Anthropic's API key is no longer referenced anywhere in src/.

4. Anthropic models are still reachable post-Task-9 via OpenRouter slugs (e.g. anthropic/claude-sonnet-4-6). The gateway routes them. No capability is lost.

Acceptance criteria:
- src/resound/classifiers/claude.py is deleted.
- "anthropic" no longer appears in pyproject.toml dependencies.
- pip install -e . succeeds without anthropic in deps.
- .env.example has no RESOUND_CLASSIFIER_PROVIDER, RESOUND_CLASSIFIER_MODEL, or ANTHROPIC_API_KEY references (commented or otherwise).
- README.md grep for "Claude" and "Anthropic" shows zero matches (other than reachable-via-OpenRouter context, if any).
- pytest still collects (existing tests don't import ClaudeClassifier).
'@

# ----------------------------------------------------------------------------
# Subtask 9.2 — Add build_classify_prompt free function
# ----------------------------------------------------------------------------

$title_9_2 = 'Add build_classify_prompt free function; delete build_classify_messages'

$desc_9_2 = 'Replace the (system, [{user}]) message-pair shape with a single string suitable for gateway.complete(). Both Pipeline (for audit) and Classifier (for gateway call) will share this function.'

$details_9_2 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #37).

File: src/resound/prompts/classify.py

ADD this function (replaces the existing build_classify_messages):

def build_classify_prompt(raw: RawSignal, brand_context: str) -> str:
    """Single-string prompt for the gateway chat-completion shape.

    OpenRouterGateway sends messages=[{role:user, content: prompt}] internally,
    so any system framing must live inside the prompt itself. Modern
    instruction-tuned models (Claude, GPT, Gemini) handle a leading
    "You are a classifier..." block at the top of a user message
    equivalently to a separate system message in practice.

    Used by:
      * OpenRouterClassifier.classify() — for the actual gateway call
      * Pipeline.run_once() — pre-built once for both success-path
        record_llm_call(prompt=...) and failure-path record_llm_failure(prompt=...)
    """
    system = CLASSIFY_PROMPT_V1.format(
        brand_context=brand_context or "(no additional context)"
    )
    user = SIGNAL_TEMPLATE.format(
        source=raw.source,
        posted_at=raw.posted_at.isoformat(),
        author=raw.author_handle or "(unknown)",
        url=raw.url or "(no url)",
        content=raw.content,
    )
    return f"{system}\n\n---\n\n{user}"

DELETE the existing build_classify_messages function (lines 71-81). It has zero remaining callers post-Task-9 because ClaudeClassifier (subtask 9.1) and OpenRouterClassifier's old code path (subtask 9.4) are both gone.

File: src/resound/prompts/__init__.py (if it has explicit exports)
- Replace any export of build_classify_messages with build_classify_prompt.

CRITICAL constraints:

1. The separator between system and user blocks is exactly "\n\n---\n\n" (newline, newline, three dashes, newline, newline). This makes the boundary visible to the model without being too instruction-heavy. Don't use SYSTEM:/USER: role labels — those imply a chat structure the model may try to continue.

2. Do NOT call gateway.complete() with system inside response_schema or any other channel. The locked gateway API per #10 has only (stage, prompt, response_schema). All framing goes inside the prompt string.

3. The function is pure — no I/O, no env reads, no logging. Same testability as the old build_classify_messages.

Acceptance criteria:
- build_classify_prompt(raw, brand_context) returns a str matching the documented format.
- build_classify_messages no longer exists in src/resound/prompts/classify.py or anywhere else.
- pytest collection includes any tests for the new function (none required at this subtask — covered in 9.7).
- grep for "build_classify_messages" across the repo shows zero matches.
'@

# ----------------------------------------------------------------------------
# Subtask 9.3 — Add JSON_MODE sentinel + make_fallback_classification
# ----------------------------------------------------------------------------

$title_9_3 = 'Add JSON_MODE sentinel and make_fallback_classification free function'

$desc_9_3 = 'Two small public-API additions: JSON_MODE constant in gateway/__init__.py and make_fallback_classification(reason) in classifiers/__init__.py. Both are consumed by 9.4, 9.5, and 9.7.'

$details_9_3 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #38, #40).

CHANGE 1 — JSON_MODE sentinel:

File: src/resound/gateway/__init__.py

Add at module level (after the existing imports, before the existing __all__):

JSON_MODE: dict = {}
"""Sentinel passed as ``response_schema`` to request JSON-mode output.

Per design #2, the gateway uses ``response_schema`` only as a presence flag
(truthy = request JSON mode, with prompt-suffix fallback for models that
lack native support). The schema content itself is NOT validated by the
gateway — callers parse with their own Pydantic models. Use this constant
rather than constructing an ad-hoc empty dict so intent is explicit at
every call site."""

Add "JSON_MODE" to __all__:

__all__ = [
    "LLMGateway",
    "LLMResponse",
    "OpenRouterGateway",
    "load_models_config",
    "StageConfig",
    "ModelsConfig",
    "build_gateway",
    "JSON_MODE",  # NEW
    "LLMGatewayError",
    "LLMGatewayConfigError",
    "LLMGatewayAuthError",
    "LLMGatewayExhaustedError",
    "LLMGatewayTimeoutError",
    "LLMGatewayParseError",
]

CHANGE 2 — make_fallback_classification:

File: src/resound/classifiers/__init__.py

Add this free function (after build_classifier or wherever the file flows naturally; signature shown without the rest of the file structure):

def make_fallback_classification(reason: str) -> Classification:
    """Stub Classification returned when an LLM call or its parse fails.

    Used by:
      * OpenRouterClassifier._parse() — when gateway-returned content
        doesn't deserialize into a Classification (parse failure → audit
        row still success=True; content preserved in llm_calls.response_content
        for forensics).
      * Pipeline.run_once() — when classifier.classify() raises
        LLMGatewayError (gateway failure → audit row success=False via
        record_llm_failure).

    The stub's is_about_brand=False and action_class=IGNORE cause the
    existing RulesRouter to map it to matched_rule="ignored_by_classifier",
    which Pipeline then counts as stats.ignored (not stats.routed).
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

Required imports at the top of the file:

from resound.models import (
    ActionClass,
    Classification,
    Sentiment,
    Severity,
)

Add "make_fallback_classification" to __all__:

__all__ = ["OpenRouterClassifier", "build_classifier", "make_fallback_classification"]

CRITICAL constraints:

1. JSON_MODE is intentionally an empty dict, NOT None. The gateway's complete() method checks `response_schema is not None` to decide whether to request JSON mode (per #2). An empty dict is truthy enough for that check.

2. JSON_MODE is intentionally untyped beyond `dict` — do NOT use TypeAlias or Literal[{}]. The flag-only-sentinel posture from #2 means the type is intentionally weak.

3. make_fallback_classification does NOT take a RawSignal argument. The existing _fallback method on OpenRouterClassifier accepted raw but never used it (verified at src/resound/classifiers/openrouter.py:97-108 pre-task-9). Cleaner signature.

4. The reason string ends up in BOTH the summary field (with prefix "[classifier fallback: ...]" — visible in dashboards) AND the reasoning field (raw, for downstream filters). This duplication is intentional per the existing pattern.

Acceptance criteria:
- from resound.gateway import JSON_MODE works at the public API.
- from resound.classifiers import make_fallback_classification works at the public API.
- JSON_MODE is type dict, value {} (empty dict).
- make_fallback_classification("test") returns a Classification with is_about_brand=False, area="other", action_class=IGNORE, confidence=0.0, summary contains "test", reasoning == "test".
- Both additions are exported in their respective __all__ lists.
- pytest still collects.
'@

# ----------------------------------------------------------------------------
# Subtask 9.4 — Refactor OpenRouterClassifier to use gateway
# ----------------------------------------------------------------------------

$title_9_4 = 'Refactor OpenRouterClassifier to use gateway and return tuple'

$desc_9_4 = 'Rewrite OpenRouterClassifier as a thin gateway wrapper. Remove direct OpenAI client; classify() returns tuple[Classification, LLMResponse]; parse failures return stub-as-data; gateway exceptions propagate.'

$details_9_4 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #36, #39, #40).

File: src/resound/classifiers/openrouter.py

REPLACE the entire OpenRouterClassifier class with this implementation. The new file should be ~50 lines total (down from ~109).

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
        # Imported here to avoid circular import (classifiers.__init__ imports this module)
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

CRITICAL constraints:

1. The Classifier ABC's classify() method's RETURN TYPE changes from `Classification` to `tuple[Classification, LLMResponse]`. Update the ABC at src/resound/core/classifier.py to match. This is a contract change; FakeClassifier in tests/test_pipeline.py needs the corresponding update (handled in subtask 9.7).

2. The classifier does NOT catch LLMGatewayError or any of its subclasses. Gateway exceptions propagate up to Pipeline.run_once(), which has the layered backstop per #42 (subtask 9.5). The OPEN of the try-block in subtask 9.5 surrounds classifier.classify(), and the gateway error path lives there.

3. The classifier DOES catch JSON parse failures and Pydantic validation failures, returning a stub via make_fallback_classification. These do NOT propagate. Per #40, parse failures are stub-as-data.

4. The classifier does NOT have memory or brand_slug references. Audit-row writes happen in Pipeline (per #36).

5. The static _fallback method from the old code is GONE. Replaced by the free function make_fallback_classification (subtask 9.3).

6. The _parse method does NOT take RawSignal anymore. The old version had `_parse(text, raw)` but never used raw. Drop the parameter.

7. The local `from resound.classifiers import make_fallback_classification` import inside _parse is intentional — it avoids a circular import (classifiers/__init__.py imports this module). Module-level import would fail at collection time.

Acceptance criteria:
- OpenRouterClassifier.__init__ takes one argument: gateway: LLMGateway.
- classify() returns a 2-tuple of (Classification, LLMResponse).
- gateway.complete() is called exactly once per classify() with stage="classify", prompt=<built via build_classify_prompt>, response_schema=JSON_MODE.
- Parse failures return a stub Classification, not raise.
- Gateway exceptions are NOT caught — they propagate.
- The file is roughly half its previous size (~50 lines vs ~109).
- pytest still collects (failures expected — tests are rewritten in 9.7).
'@

# ----------------------------------------------------------------------------
# Subtask 9.5 — Refactor Pipeline.run_once and build_classifier factory
# ----------------------------------------------------------------------------

$title_9_5 = 'Refactor Pipeline.run_once with three-tier exception backstop and audit writes'

$desc_9_5 = 'Wire the Pipeline to write llm_calls audit rows on success and failure paths. Replace the single broad-except block with the layered backstop. Update build_classifier factory.'

$details_9_5 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #36, #39, #42).

CHANGE 1 — build_classifier factory:

File: src/resound/classifiers/__init__.py

Replace the existing build_classifier() with:

def build_classifier(brand_slug: str) -> Classifier:
    """Build the default classifier for a brand. Loads brand-specific
    models.yaml overrides via the gateway factory."""
    return OpenRouterClassifier(build_gateway(brand_slug))

Required new import at the top:

from resound.gateway import build_gateway

The provider toggle (RESOUND_CLASSIFIER_PROVIDER) is gone; the function takes brand_slug instead of being argument-less. Pipeline (subtask 9.5 next change) is the only caller and passes brand.slug.

CHANGE 2 — Pipeline.run_once:

File: src/resound/pipeline.py

Replace the per-signal classification block (currently lines 68-99 inside the inner for loop) with this expanded version. Imports needed at the top of the file:

import time
from resound.classifiers import build_classifier, make_fallback_classification
from resound.gateway import (
    LLMGatewayAuthError,
    LLMGatewayConfigError,
    LLMGatewayError,
)
from resound.prompts.classify import build_classify_prompt

Remove the existing import:

from resound.classifiers import build_classifier   # if currently arg-less, signature changes

Pipeline.__init__ change — exactly one line of body change:

    self.classifier = classifier or build_classifier(brand.slug)

(was: self.classifier = classifier or build_classifier())

The new per-signal block inside `for raw in signals:` (replaces lines 68-99 in the current file):

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

                # Stub flows through router/memory/feedback like a normal classification.
                # The router treats stub's is_about_brand=False/action_class=IGNORE
                # as matched_rule="ignored_by_classifier", which the branch below
                # counts as stats.ignored.
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

CRITICAL constraints:

1. The order of except clauses MATTERS. (LLMGatewayConfigError, LLMGatewayAuthError) MUST come before LLMGatewayError because the former are subclasses of the latter (per the locked hierarchy in design #13). Python's except clauses are matched top-to-bottom; the broader catch must come last.

2. stats.classified ONLY increments on the success path inside the try block. Do not increment in the except branches. This keeps the "classified count" honest as "number of successfully classified signals."

3. The current `continue` skip on classifier failure (pipeline.py:81-83) is REMOVED. Stubs flow through router/memory/feedback. The existing ignored_by_classifier branch handles them naturally — no special-case logic needed.

4. Pipeline does NOT hold a gateway reference (per #39). It only imports LLMGatewayError, LLMGatewayConfigError, LLMGatewayAuthError for the except clauses. There is no self.gateway attribute.

5. The prompt is pre-built BEFORE the try block so it's available in BOTH success-path record_llm_call and failure-path record_llm_failure. The classifier internally rebuilds the same prompt via the shared free function — duplicate work is nanoseconds; no drift risk because both call sites use build_classify_prompt.

6. getattr(exc, "attempts", 1) handles the fact that only LLMGatewayExhaustedError carries an attempts attribute (per design #13). Other LLMGatewayError subclasses (Timeout, Parse) don't have it — the default is 1 because at least one attempt was made before the timeout/parse-fail fired.

7. The broad `except Exception` clause does NOT call record_llm_failure. There's no properly-formed LLMGatewayError to pass to it, and constructing a fake one would lie about the source. The logger.exception captures the traceback for forensics.

Acceptance criteria:
- Pipeline.__init__ unchanged in signature (no gateway kwarg).
- Per-signal block produces an llm_calls row on every successful classify (visible via SqlMemory query).
- Per-signal block produces an llm_calls failure row on every LLMGatewayError except Config/Auth.
- LLMGatewayConfigError and LLMGatewayAuthError propagate out of run_once() to the caller.
- Unexpected exceptions produce a stub but no llm_calls row, with logger.exception capturing details.
- stats.classified increments only on success.
- stats.errors increments on both LLMGatewayError and broad Exception paths.
- A failed classification still produces signals/classifications/routes rows (no schema-level NULL FKs).
- Stub Classifications route to "ignored_by_classifier" via the router, counted as stats.ignored.
- Existing tests in tests/test_pipeline.py do not pass yet — they need the FakeClassifier update from subtask 9.7.
'@

# ----------------------------------------------------------------------------
# Subtask 9.6 — Update cli.py healthcheck for models.yaml resolution
# ----------------------------------------------------------------------------

$title_9_6 = 'Update cli.py healthcheck to show classify model with brand-override status'

$desc_9_6 = 'Replace env-var-based model display with models.yaml resolution. Show classify model, source (override vs default), fallback chain, timeout, and OPENROUTER_API_KEY check.'

$details_9_6 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #44).

File: src/resound/cli.py

Replace lines 87-96 (the existing classifier provider/model/API key block) with:

    from resound.gateway import load_models_config

    global_cfg = load_models_config(brand_slug=None)
    brand_cfg = load_models_config(brand_slug=brand)
    classify = brand_cfg.get_stage_config("classify")
    global_classify_model = global_cfg.get_stage_config("classify").model

    if classify.model != global_classify_model:
        source = f"brand override (brands/{brand}/models.yaml)"
    else:
        source = "config/models.yaml (global default)"

    console.print(f"  classify model: {classify.model}")
    console.print(f"    source: {source}")
    fallback_str = ", ".join(classify.fallbacks) if classify.fallbacks else "(none)"
    console.print(f"    fallbacks: {fallback_str}")
    console.print(f"    timeout: {classify.timeout_s}s")

    if not env("OPENROUTER_API_KEY"):
        console.print("[red]✗ OPENROUTER_API_KEY not set[/]")
    else:
        console.print("[green]✓ OPENROUTER_API_KEY set[/]")

The import `from resound.gateway import load_models_config` can go at the top of the file with the other imports — the in-function form is shown above for clarity.

REMOVE these now-orphan references from cli.py (if present):
- Any `env("RESOUND_CLASSIFIER_PROVIDER", ...)` call
- Any `env("RESOUND_CLASSIFIER_MODEL", ...)` call
- Any conditional that checks `provider == "anthropic"` or branches on ANTHROPIC_API_KEY

CRITICAL constraints:

1. The brand-override detection logic compares the resolved classify.model from `load_models_config(brand)` against the global default's classify.model. If they differ, the brand has an override. This is correct for #16's field-level merge semantics — even if the brand override file exists but only overrides a different stage (e.g., filter), the classify model would still equal the global default and source label would say "global default."

2. Do NOT show all four stages. Only classify is wired in this scope (Tasks 4/5/6/8 skipped). Showing filter/routing_tiebreaker/memory_query would be misleading because nothing actually calls them per #44's rejected option B.

3. Do NOT add a dashboard URL or runtime check that requires actually hitting OpenRouter. Healthcheck must be fast and offline-capable — it's run before recording, before deployment, etc.

4. Keep the existing brand context logging from earlier in healthcheck (lines 79-86: brand name, sources, routing rules, people, channels, understanding doc). Only the model/provider/API key block changes.

Acceptance criteria:
- `resound healthcheck --brand liquiddeath` prints: classify model name (resolved from brand override per #22), source label "brand override (brands/liquiddeath/models.yaml)", the fallbacks list, the timeout in seconds, and the OPENROUTER_API_KEY status.
- `resound healthcheck --brand fulfil` (no models.yaml override per #23) prints classify model with source label "config/models.yaml (global default)".
- No environment variables prefixed with RESOUND_CLASSIFIER_ are read anywhere in cli.py.
- ANTHROPIC_API_KEY is not referenced.
- Healthcheck runs in under 200ms (no network calls).
'@

# ----------------------------------------------------------------------------
# Subtask 9.7 — Tests: classifier unit + Pipeline orchestration + smoke
# ----------------------------------------------------------------------------

$title_9_7 = 'Tests: new tests/test_classifier.py + extend tests/test_pipeline.py + smoke test'

$desc_9_7 = 'Two-file test split. New tests/test_classifier.py (~8 cases with FakeGateway). Extended tests/test_pipeline.py (~9 new cases with updated FakeClassifier). One end-to-end smoke test wiring real OpenRouterClassifier + FakeGateway + real Pipeline + real SqlMemory.'

$details_9_7 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #43).

PART 1 — New file: tests/test_classifier.py

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


PART 2 — Update tests/test_pipeline.py

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

The existing tests (test_pipeline_end_to_end, test_pipeline_dedupes_on_second_run) should still pass with this updated FakeClassifier — they construct it with fixed=Classification(...) which now matches the new __init__ signature.

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
    # Stub Classification → ignored_by_classifier → no feedback fired.
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
    # No audit row — broad except path doesn't write llm_calls.
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


PART 3 — Smoke test in tests/test_pipeline.py

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

1. Tests for the classifier (PART 1) MUST use FakeGateway, not mock the openai SDK directly. The point of #39 is that gateway is the seam — tests should mock at that seam.

2. Tests for the Pipeline (PART 2) MUST NOT import or instantiate OpenRouterGateway. They use FakeClassifier injection (existing pattern). Pipeline tests are about orchestration and audit-write behavior, not about gateway internals.

3. The smoke test (PART 3) is the ONE test that wires real classifier + Pipeline + SqlMemory together. It uses FakeGateway because we don't want network calls in CI. This is the closest test to a real `resound poll-once` invocation.

4. SqlMemory's engine.connect().execute() pattern in the assertions assumes raw SQL is acceptable for tests. If the existing test_llm_calls.py (from Task 3) uses a different query API (e.g. session-based), MIRROR that pattern for consistency. The exact query API can be adapted.

5. The _RotatingClassifier helper is for the multi-signal tests where one succeeds and one fails. Don't over-design — just a list of results, advance an index per call.

6. Tests must run on Windows (the user's platform per environment) — no POSIX-only path tricks.

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
# Execute
# ----------------------------------------------------------------------------

$subtasks = @(
    @{ title = $title_9_1; description = $desc_9_1; details = $details_9_1 },
    @{ title = $title_9_2; description = $desc_9_2; details = $details_9_2 },
    @{ title = $title_9_3; description = $desc_9_3; details = $details_9_3 },
    @{ title = $title_9_4; description = $desc_9_4; details = $details_9_4 },
    @{ title = $title_9_5; description = $desc_9_5; details = $details_9_5 },
    @{ title = $title_9_6; description = $desc_9_6; details = $details_9_6 },
    @{ title = $title_9_7; description = $desc_9_7; details = $details_9_7 }
)

$index = 0
foreach ($s in $subtasks) {
    $index++
    Write-Host "==> Creating subtask 9.$index : $($s.title)" -ForegroundColor Cyan
    task-master add-subtask `
        --parent=9 `
        --title=$($s.title) `
        --description=$($s.description) `
        --details=$($s.details)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED creating subtask 9.$index (exit $LASTEXITCODE). Stopping." -ForegroundColor Red
        Write-Host "If --details is not a recognized flag in your task-master version, edit this script" -ForegroundColor Yellow
        Write-Host "to drop --details and re-run, then use update-subtask separately to add the design notes." -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "All 7 subtasks created. Verify with: task-master show 9" -ForegroundColor Green
Write-Host "Authoritative design spec: docs/design_decisions.md (Task 9 section, decisions #35-#44)" -ForegroundColor Gray
