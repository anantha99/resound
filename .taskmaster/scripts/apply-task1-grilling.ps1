# Applies the locked Task 1 design decisions from the 2026-05-02 grilling
# session to subtasks 1.1 - 1.6 via task-master update-subtask.
#
# RUN THIS FROM A SEPARATE TERMINAL (not from inside an active Claude Code session).
# task-master is configured to spawn a child `claude` subprocess for AI writes,
# which fails when the parent is already a claude process.
#
# Usage (from project root):
#   pwsh .taskmaster/scripts/apply-task1-grilling.ps1
#
# Idempotent: update-subtask APPENDS timestamped notes; running twice duplicates.
# Run once, verify with `task-master show 1`.

$ErrorActionPreference = 'Stop'

$prompt_1_1 = @'
DESIGN LOCKED via grilling on 2026-05-02. Implement base.py per the following final spec:

LLMResponse (Pydantic BaseModel, 7 fields - keep lean):
- content: str
- model_used: str  (the model that actually returned, may differ from stage primary if fallback fired)
- tokens_in: int
- tokens_out: int
- cost_usd: float | None  (CHANGED from float - None when OpenRouter does not return usage.cost; no price-table fallback for demo)
- latency_ms: float
- raw_response: dict[str, Any]

Do NOT add stage / attempts / prompt_hash / timestamp - those belong to the audit trail layer (Task 3), not the gateway response.

LLMGateway ABC - final complete() signature (NO temperature, NO max_tokens, NO model_override):

    def complete(
        self,
        stage: str,                    # plain str (not Literal) - extensibility without code changes
        prompt: str,
        response_schema: dict | None = None,  # FLAG-ONLY: sentinel for "request JSON mode"; gateway does NOT validate against schema. Caller parses with own Pydantic models.
    ) -> LLMResponse

StageConfig (loaded from models.yaml in subtask 1.2) is the single source of truth for temperature / max_tokens / timeout_s. No per-call overrides.

Exception hierarchy - define ALL FIVE in base.py:

    class LLMGatewayError(Exception): ...                     # root; Pipeline catches broadly to skip a signal

    class LLMGatewayConfigError(LLMGatewayError): ...         # bad models.yaml, unknown stage, missing API key - FATAL, crash worker
    class LLMGatewayAuthError(LLMGatewayError): ...           # 401/403 - FATAL, do NOT trigger fallback
    class LLMGatewayExhaustedError(LLMGatewayError):
        attempts: list[tuple[str, Exception]]                 # (model, exception) per attempt; carry for audit/log
    class LLMGatewayTimeoutError(LLMGatewayError): ...        # per-stage wall-clock budget exceeded
    class LLMGatewayParseError(LLMGatewayError):
        raw_text: str                                         # carry the unparseable response for forensics

Pipeline behavior contract (document in docstring): catch LLMGatewayError broadly, mark signal errored, move on. Do NOT catch ConfigError/AuthError - let them crash the worker so operator notices.
'@

$prompt_1_2 = @'
DESIGN LOCKED via grilling on 2026-05-02. Implement models_config.py per the following final spec:

StageConfig (Pydantic BaseModel - use Pydantic for free YAML-load validation, NOT plain dataclass) - exactly 5 fields:
- model: str
- temperature: float
- max_tokens: int
- fallbacks: list[str]
- timeout_s: float          (NEW per Q3 of grilling - per-stage wall-clock cap, e.g. filter ~5s, classify ~30s, others ~10s)

Do NOT add prompt_price / completion_price (no price table for demo per Q5), provider_routing knobs, or system_prompt fields.

ModelsConfig: dict mapping stage name to StageConfig. Provide get_stage_config(stage: str) -> StageConfig that raises LLMGatewayConfigError (from base.py) on unknown stage.

load_models_config(brand_slug: str | None = None, config_dir: Path | None = None, brands_dir: Path | None = None) -> ModelsConfig

Brand override merge semantics (LOCKED):
- FIELD-LEVEL merge over global defaults. Brand override file specifies only the deltas; missing fields inherit from global.
- List fields (fallbacks) REPLACE the global list - do NOT concat. Order matters in fallback chains and concat is rarely what callers want.
- Merge happens at stage granularity: brand can override one stage entirely without touching others.

Document precedence clearly in the file header comment of both YAMLs: "brand overrides merge field-by-field over global defaults; list fields (fallbacks) replace; missing fields inherit."

Sensible built-in defaults if no yaml exists (so tests do not need fixtures): use the same values that subtask 1.6 puts in config/models.yaml.

Use existing yaml-loading pattern from resound/config.py (yaml.safe_load).
'@

$prompt_1_3 = @'
DESIGN LOCKED via grilling on 2026-05-02. Implement OpenRouterGateway per the following final spec:

Constructor (testability lift - accept all four optionals, env-default the unset ones):

    OpenRouterGateway(
        config: ModelsConfig,                  # required
        api_key: str | None = None,            # default: os.environ["OPENROUTER_API_KEY"]; raise LLMGatewayConfigError if missing
        http_referer: str | None = None,       # default: env OPENROUTER_APP_URL or "https://github.com/resound"
        app_title: str | None = None,          # default: env OPENROUTER_APP_NAME or "Resound"
        client: OpenAI | None = None,          # CRITICAL for testability - lets tests inject mock client without monkeypatching openai.OpenAI
    )

Per-brand instance - one gateway per Pipeline (Pipeline wiring deferred to Task 9, do NOT touch pipeline.py here).

Retry orchestration (LOCKED - both knobs matter):
- Per-model: max 3 attempts with exponential backoff (2s, 4s, 8s) on TRANSIENT errors only: 5xx, openai timeout exceptions, 429 rate limits.
- Fallback chain: each fallback model gets a FRESH 3-attempt budget. Do not share the budget across the chain - point of fallbacks is to escape an outage on the primary provider.
- Per-stage wall-clock cap from StageConfig.timeout_s. Once exceeded, raise LLMGatewayTimeoutError even if retries/fallbacks remain.

Fallback trigger (NARROW - most 4xx are bugs, not fallback-able):
- TRIGGER fallback on: 404 (model not found), 422 (unprocessable), 413 (context too long), OpenRouter "no available provider" responses.
- FATAL - raise immediately, do NOT retry/fallback: 400 (malformed request -> LLMGatewayConfigError), 401 (LLMGatewayAuthError), 403 (LLMGatewayAuthError).
- Reasoning: if the API key is bad, three more requests confirming it is still bad just wastes latency.

When all primary retries + all fallback models exhausted: raise LLMGatewayExhaustedError(attempts=[(model, exc), ...]).

Cost tracking (LOCKED for demo - no price table):
- ALWAYS pass extra_body={"usage": {"include": true}} on every chat completion (free, gives us OpenRouter-authoritative cost in response.usage.cost).
- If response.usage.cost is present: cost_usd = that value.
- If missing: cost_usd = None + log warning. Do NOT fall back to a hardcoded price table; do NOT fetch /models. (Demo scope; revisit post-demo.)

LLMResponse population:
- model_used: the model that actually returned (NOT necessarily the primary - reflects fallback outcome).
- latency_ms: time.perf_counter() delta around the WHOLE complete() call (including all retries/fallbacks), so audit reflects user-observed latency.
- raw_response: keep the full dict - escape hatch for Task 3 audit trail.

Per-call request setup:
- response_format={"type": "json_object"} when response_schema is not None (subject to JSON-mode detection in subtask 1.4).
- max_tokens / temperature pulled from StageConfig (NOT from complete() args - those args were dropped per Q8).
'@

$prompt_1_4 = @'
DESIGN LOCKED via grilling on 2026-05-02. Implement JSON-mode fallback per the following final spec - TRY-AND-DETECT with per-process cache (NOT a hardcoded blocklist).

Reasoning the user picked this: hardcoded blocklists rot fast (OpenRouter JSON-mode support matrix changes weekly). Try-and-detect costs one wasted request per new model per process, then never again.

Algorithm:

1. Maintain a per-instance cache on OpenRouterGateway: self._no_json_mode_models: set[str] = set()
2. When complete() called with response_schema is not None:
   a. If model already in self._no_json_mode_models -> skip native JSON mode, go straight to step 4.
   b. Else: send request with response_format={"type": "json_object"}.
3. On 400 response containing "response_format" or "json_object" in the error message:
   a. Log warning: "model X does not support native JSON mode; falling back to prompt-suffix extraction"
   b. Add model to self._no_json_mode_models cache.
   c. Retry the SAME call (same prompt) once without response_format and with prompt suffix appended.
4. Prompt-suffix mode:
   a. Append "\n\nRespond with JSON only, no additional prose." to the prompt.
   b. Send request without response_format.
5. ALWAYS run regex extraction as a defensive parse step on response.choices[0].message.content, EVEN when native JSON mode succeeded (defends against models that occasionally wrap JSON in prose):
   a. Pattern: re.search(r"\{.*\}", text, re.DOTALL) - same as existing classifiers/openrouter.py:69.
   b. If a match is found, that is the JSON to return as LLMResponse.content.
   c. Validate that match parses as JSON (json.loads) - if it does not, treat as parse failure.
6. If no JSON object found OR json.loads fails after both JSON-mode attempt and regex extraction:
   raise LLMGatewayParseError(raw_text=<full response text>) - see exception spec in subtask 1.1.

Note: gateway does NOT validate the JSON against response_schema (response_schema is flag-only per Q2). Caller validates with their own Pydantic model.

Per-process cache implications:
- Cache lives on the OpenRouterGateway instance. Since Pipeline holds one gateway per brand, cache is effectively per-brand-per-process.
- Tests should be able to pre-seed the cache to skip the detection round trip in fixtures.
- No persistence across process restarts - that is fine; one wasted request on cold start is acceptable.
'@

$prompt_1_5 = @'
DESIGN LOCKED via grilling on 2026-05-02. Implement gateway/__init__.py per the following final spec.

Public exports (__all__) - INCLUDE the exception classes from subtask 1.1, the plan originally omitted them:

    __all__ = [
        # Core abstractions
        "LLMGateway",
        "LLMResponse",
        "OpenRouterGateway",
        # Config
        "load_models_config",
        "StageConfig",
        "ModelsConfig",
        # Factory
        "build_gateway",
        # Exceptions - callers (Pipeline, CLI) need these to catch correctly
        "LLMGatewayError",
        "LLMGatewayConfigError",
        "LLMGatewayAuthError",
        "LLMGatewayExhaustedError",
        "LLMGatewayTimeoutError",
        "LLMGatewayParseError",
    ]

build_gateway() factory - brand-aware one-liner (gateway is per-brand per Q1):

    def build_gateway(brand_slug: str) -> OpenRouterGateway:
        """Build a per-brand OpenRouterGateway with merged config."""
        return OpenRouterGateway(config=load_models_config(brand_slug))

That is it - one line. The explicit OpenRouterGateway(config=..., client=...) form stays available for tests; build_gateway is the 95% public path.

CRITICAL - Pipeline wiring is DEFERRED to Task 9:
- Do NOT modify src/resound/pipeline.py in this task.
- Do NOT add a `gateway` parameter to Pipeline.__init__ here.
- The gateway exists standalone with isolated unit tests at the end of Task 1.
- Task 9 ("Refactor Classifiers to Use Gateway") is where Pipeline starts taking a gateway parameter and classifiers route through it.

This keeps Task 1 diff small, reviewable, and decoupled - gateway module is shipped & tested in isolation; integration follows in Task 9.

Module-level docstring should explain: "Cross-cutting LLM gateway for Resound. All model calls go through OpenRouter via this abstraction. Per-brand instance constructed by Pipeline (wiring lands in Task 9)."
'@

$prompt_1_6 = @'
DESIGN LOCKED via grilling on 2026-05-02. config/models.yaml content - per-stage including the NEW timeout_s field (added to StageConfig in subtask 1.2) and 1-element fallbacks for ALL stages (was empty for routing_tiebreaker / memory_query in original plan).

defaults:
  filter:
    model: openai/gpt-4.1-mini
    temperature: 0.0
    max_tokens: 64
    timeout_s: 5
    fallbacks:
      - anthropic/claude-haiku-4-5
      - google/gemini-2.0-flash

  classify:
    model: anthropic/claude-sonnet-4-6
    temperature: 0.1
    max_tokens: 1024
    timeout_s: 30
    fallbacks:
      - openai/gpt-4.1
      - google/gemini-2.5-pro

  routing_tiebreaker:
    model: openai/gpt-4.1-mini
    temperature: 0.0
    max_tokens: 128
    timeout_s: 10
    fallbacks:
      - anthropic/claude-haiku-4-5      # ADDED - original plan had empty list; cheap insurance against OpenAI hiccups

  memory_query:
    model: openai/gpt-4.1-mini
    temperature: 0.0
    max_tokens: 256
    timeout_s: 10
    fallbacks:
      - anthropic/claude-haiku-4-5      # ADDED - same reasoning

YAML header comment - explicitly state:
1. Stage purpose (filter = fast triage, classify = deep work, etc.)
2. Why these models chosen (and that they are DEMO-PROVISIONAL - see note below).
3. Brand override semantics: "files in brands/<slug>/models.yaml override these field-by-field; list fields (fallbacks) replace globally."

DEMO-PROVISIONAL note - IMPORTANT (per user feedback during grilling):
These model picks are reasonable production defaults but should be REVISITED at demo time (Task 21 "Verify Model Swap Demo Flow"). Closer to the demo, swap in current top-tier models that are also efficient and cheap as of 2026. Do not lock these picks in for the demo recording without re-evaluating against latest available models on OpenRouter.

Pre-ship verification - DO NOT trust these model names without confirming they are live on the user OpenRouter account. Run a one-shot smoke test (5-line Python: hit each model with "ping", confirm 200) before marking subtask 1.6 done. Catches typos and access-tier issues that would 404 on first real run.

Ensure config/ directory exists at project root (create if needed - currently project has brands/ but no config/).
'@

$updates = @(
    @{ id = '1.1'; prompt = $prompt_1_1 },
    @{ id = '1.2'; prompt = $prompt_1_2 },
    @{ id = '1.3'; prompt = $prompt_1_3 },
    @{ id = '1.4'; prompt = $prompt_1_4 },
    @{ id = '1.5'; prompt = $prompt_1_5 },
    @{ id = '1.6'; prompt = $prompt_1_6 }
)

foreach ($u in $updates) {
    Write-Host "==> Updating subtask $($u.id) ..." -ForegroundColor Cyan
    task-master update-subtask --id=$($u.id) --prompt=$($u.prompt)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED on $($u.id) (exit $LASTEXITCODE). Stopping." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "All 6 subtasks updated. Verify with: task-master show 1" -ForegroundColor Green
