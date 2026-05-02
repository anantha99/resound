# Resound — Design Decisions

Locked design decisions, organized by feature area. Each entry cites the task it was decided in and the reasoning, so future tasks can tell whether a decision still applies or needs to be re-litigated.

When a decision changes, **update this file in the same PR as the code change** and add a note under "Superseded decisions" at the bottom.

---

## Task 1 — LLM Gateway Abstraction

Locked in grilling session on **2026-05-02**. Source task: `task-master show 1`.

### Architecture

| # | Decision | Rationale | Rejected alternatives |
|---|---|---|---|
| 1 | **Per-brand gateway instance.** One `OpenRouterGateway` per `Pipeline`, constructed at brand load. | Mirrors the existing per-brand pattern for `Classifier`/`Router`/`Memory` in `Pipeline.__init__`. OpenAI client is cheap to instantiate. | Process-level singleton with `{brand_slug: ModelsConfig}` registry — would force every call site to thread `brand_slug`, and `stage` alone would no longer fully resolve the model. |
| 2 | **`response_schema` is flag-only.** `dict \| None` sentinel meaning "request JSON mode." Gateway does NOT validate the response against the schema. | Matches what `classifiers/openrouter.py` does today. Callers already have Pydantic models — second validation layer would be duplicate work that can disagree. OpenRouter's strict-JSON-schema mode coverage is patchy across models. | Pass-through JSON Schema with gateway validation; typed parse with `response_model: type[BaseModel]`. Both can be added later without breaking callers. |
| 3 | **Retry budget is fresh per fallback model.** Per-model: 3 attempts with exp backoff (2/4/8s) on transient errors (5xx/429/timeout). Each fallback model gets its own fresh 3-attempt budget. | Point of fallbacks is to escape an outage on the *primary provider* — sharing the budget defeats that. Bounded by the per-stage `timeout_s`. | Shared budget across the chain. |
| 4 | **Per-stage wall-clock cap (`timeout_s`).** Hard ceiling per `complete()` call; raises `LLMGatewayTimeoutError` even if retries/fallbacks remain. Filter ~5s, classify ~30s, others ~10s. | Without this, one slow signal can stall the pipeline for ~45s+ (3 retries × backoff × multiple fallbacks). Per-stage rather than global because filter ≠ classify in latency budget. | Single global timeout. |
| 5 | **Fallback trigger is narrow.** Only 404 / 422 / 413 / OpenRouter "no available provider" trigger fallback. 400 / 401 / 403 are **fatal** — raise immediately. | Wasting 3 round trips to confirm the API key is still bad helps no one. 400/401/403 are bugs to fix, not to fall back from. | Plan's original "any 4xx (non-429)" — too broad. |
| 6 | **JSON mode: try-and-detect with per-process cache.** First call uses native JSON mode; on 400 with `response_format`/`json_object` in the error, mark `model → no_json_mode` in an instance-level set, retry once with prompt suffix + regex extraction. **Always** run regex extraction defensively (even on JSON-mode success). | Hardcoded blocklists rot fast (OpenRouter changes weekly); operators shouldn't have to know which models support JSON mode. One wasted request per cold-start model is acceptable. | Hardcoded blocklist; hardcoded allowlist; per-model annotation in `models.yaml`; never use native JSON mode. |
| 7 | **Cost from OpenRouter only — no price table for demo.** Always include `extra_body={"usage": {"include": true}}`. If `response.usage.cost` present → use it. If missing → `cost_usd = None` + warning. No hardcoded prices, no `/models` fetch. | Demo scope cut. Live price tables rot fast and aren't worth implementing for a one-shot demo. Revisit post-demo if the audit trail in Task 3 needs cost completeness. | Hardcoded `MODEL_PRICES` dict; YAML-defined prices; `GET /models` fetch at startup; per-call `GET /generation/{id}`. |

### API surface

| # | Decision | Rationale | Rejected alternatives |
|---|---|---|---|
| 8 | **No `model_override` on `complete()`.** CLI testing (Task 10) builds a one-off gateway with custom config. | Demo scope. The override path can be added in one line later without breaking existing callers. | `complete(..., model_override: str \| None)` with override skipping fallbacks. |
| 9 | **No per-call `temperature` / `max_tokens`.** `StageConfig` is the single source of truth, read by the gateway per call. | Plan had function-default `0.1` / `1024` AND fields in `StageConfig` — the function defaults would silently override YAML. Cleaner to drop them entirely. | Keep them as `None`-defaulted overrides falling through to `StageConfig`. |
| 10 | **Final `complete()` signature**: `complete(stage: str, prompt: str, response_schema: dict \| None = None) -> LLMResponse`. | Smallest surface that does the job. Adding more knobs is one-line work later. | Original plan signature with temperature, max_tokens, response_schema, etc. |
| 11 | **`LLMResponse` stays lean — 7 fields**: `content`, `model_used`, `tokens_in`, `tokens_out`, `cost_usd: float \| None`, `latency_ms`, `raw_response`. | `stage` is redundant (caller passed it). `attempts` is captured by `LLMGatewayExhaustedError` on failure path. `prompt_hash`/`timestamp` belong to the audit trail layer (Task 3), not the gateway. `raw_response` is the escape hatch. | Adding `stage`, `attempts`, `prompt_hash`, `timestamp` directly on success-path responses. |
| 12 | **`stage: str`** (plain string, not `Literal`). Unknown stage → `LLMGatewayConfigError` at lookup time. | Matches existing taskmaster note (2026-05-02): allows extensibility without code changes. | `Literal['filter' \| 'classify' \| 'routing_tiebreaker' \| 'memory_query']`. |

### Errors

| # | Decision | Rationale | Rejected alternatives |
|---|---|---|---|
| 13 | **Hierarchical exception tree, 5 leaf classes** under `LLMGatewayError`: `LLMGatewayConfigError`, `LLMGatewayAuthError`, `LLMGatewayExhaustedError(attempts=...)`, `LLMGatewayTimeoutError`, `LLMGatewayParseError(raw_text=...)`. | Hierarchy lets Pipeline catch `LLMGatewayError` broadly (skip a signal, move on) while letting Config/Auth errors bubble out and crash the worker so the operator notices. | Single `LLMGatewayError` (loses recoverability info); flat sibling classes (broad-catch becomes painful). |
| 14 | **Config/Auth errors are FATAL** — Pipeline does not catch them. Exhausted/Timeout/Parse errors are caught broadly via `LLMGatewayError`, signal marked `errored`, pipeline continues. | If `models.yaml` is malformed or `OPENROUTER_API_KEY` is wrong, the worker should die loudly at startup, not silently skip every signal. | Catch-all error handling. |

### Config

| # | Decision | Rationale | Rejected alternatives |
|---|---|---|---|
| 15 | **`StageConfig` is a Pydantic `BaseModel`** with exactly 5 fields: `model`, `temperature`, `max_tokens`, `fallbacks`, `timeout_s`. | Pydantic gives free YAML-load validation — type errors at startup, not at runtime. `timeout_s` was added during grilling (Q3) and is per-stage. | Plain `dataclass` (no validation); adding `prompt_price` / `provider_routing` / `system_prompt` (out of demo scope). |
| 16 | **Brand override merge is field-level** (over global defaults). Brand override file specifies only deltas; missing fields inherit. **List fields (`fallbacks`) replace whole** — do not concat. | DRY brand files. List concat for fallback chains is rarely what callers want — order matters and you usually want to *replace* the chain for a brand. | Stage-level replacement (verbose); list concat. |
| 17 | **Default models in `config/models.yaml` (subtask 1.6) are DEMO-PROVISIONAL.** Ship reasonable defaults now (`claude-sonnet-4-6` for classify, `gpt-4.1-mini` elsewhere, with 1-element fallbacks for *all* stages). **Revisit at demo time** with current top-tier efficient+cheap models. | User flagged in grilling: model availability/quality on OpenRouter churns fast. A model picked weeks before a demo may be superseded. See `feedback_demo_model_selection.md` in user memory. | Lock in models now and forget about them. |

### Wiring

| # | Decision | Rationale | Rejected alternatives |
|---|---|---|---|
| 18 | **`OpenRouterGateway` constructor**: `(config, api_key=None, http_referer=None, app_title=None, client=None)` — env defaults for the optionals, `client` injectable for tests. | `client` injection makes every retry/fallback test 5 lines instead of 50 (no monkeypatching `openai.OpenAI`). Env defaults match the existing classifier pattern. | Constructor takes `ModelsConfig` only (testability tax). |
| 19 | **`build_gateway(brand_slug)` is the public one-liner**: returns `OpenRouterGateway(config=load_models_config(brand_slug))`. The explicit `OpenRouterGateway(config=..., client=...)` form remains for tests. | Public API stays brand-shaped; tests can bypass it. | Factory takes `ModelsConfig` (verbose for callers); only the constructor (no factory). |
| 20 | **Pipeline wiring is DEFERRED to Task 9.** Task 1 ships the gateway module standalone with isolated tests. **Do NOT modify `src/resound/pipeline.py`** in Task 1. | Keeps Task 1's diff small and reviewable. Gateway is testable in isolation; integration follows naturally when classifiers refactor onto it. | Wire the gateway into `Pipeline.__init__` immediately and create unused parameters until Task 9. |

---

## Cross-task implications

Decisions here that affect other tasks — keep in sync when those tasks land:

- **Task 3 (`llm_calls` audit table)**: schema must capture what `LLMResponse` doesn't (stage, prompt hash, timestamp, signal_id, brand_slug, attempts on success-path-after-fallback). Pipeline owns these, not the gateway. (Per #11.)
- **Task 9 (refactor classifiers)**: this is when `Pipeline.__init__` gains a `gateway` parameter (per #20) and `OpenRouterClassifier` is rewritten to call `gateway.complete(stage="classify", ...)` rather than its own OpenAI client. The existing `classifiers/openrouter.py` JSON parsing logic should be lifted into the gateway's regex-extraction path (per #6).
- **Task 10 (CLI model testing)**: must build a one-off gateway with a custom `ModelsConfig` (per #8 — no `model_override` on `complete()`).
- **Task 21 (verify demo flow)**: revisit model picks in `config/models.yaml` against current top-tier efficient+cheap models on OpenRouter (per #17).

---

## Superseded decisions

_None yet. When a decision is replaced, move the original here with a note explaining the new decision and which task changed it._
