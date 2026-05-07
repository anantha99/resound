# Task ID: 1

**Title:** Implement LLM Gateway Abstraction Layer

**Status:** done

**Dependencies:** None

**Priority:** high

**Description:** Create the cross-cutting LLM gateway module that centralizes all model calls through OpenRouter with retry logic, fallback chains, and cost tracking.

**Details:**

Create `src/resound/gateway/` module with:

1. `base.py` - Define `LLMGateway` ABC with method:
```python
def complete(
    self,
    stage: str,  # 'filter' | 'classify' | 'routing_tiebreaker' | 'memory_query'
    prompt: str,
    response_schema: dict | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> LLMResponse
```
Define `LLMResponse` dataclass: `content`, `model_used`, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `raw_response`.

2. `openrouter.py` - Implement `OpenRouterGateway`:
   - Use `openai` SDK with `base_url="https://openrouter.ai/api/v1"`
   - Set required headers: `HTTP-Referer`, `X-Title`
   - Implement retry with exponential backoff (max 3 retries) for 5xx/timeout/429
   - Implement fallback chain: on 4xx (non-429), try next model in `fallbacks` list
   - Request JSON-mode output when `response_schema` provided
   - Fallback to "JSON only, no prose" prompt suffix + regex extraction for non-JSON-mode models
   - Parse cost from OpenRouter's `usage.cost` field, compute from tokens × price if unavailable

3. `models_config.py` - Load and merge models.yaml:
   - Global defaults from `config/models.yaml`
   - Per-brand overrides from `brands/<brand>/models.yaml`
   - Dataclass: `StageConfig` with `model`, `temperature`, `max_tokens`, `fallbacks`

4. `__init__.py` - Export `OpenRouterGateway`, `LLMResponse`, `load_models_config`

**Test Strategy:**

Unit tests with mocked OpenRouter API:
- Test happy path returns valid LLMResponse with correct fields
- Test rate limit (429) triggers exponential backoff and retry
- Test provider error (5xx) triggers retry up to 3 times
- Test permanent error (4xx) falls through to next fallback model
- Test all fallbacks fail raises `LLMGatewayError`
- Test JSON-mode extraction with valid and malformed responses
- Test models.yaml loading with global defaults and brand overrides

## Subtasks

### 1.1. Create base.py with LLMGateway ABC and LLMResponse dataclass

**Status:** done  
**Dependencies:** None  

Define the abstract base class LLMGateway with the complete() method signature and create the LLMResponse dataclass with all required fields for tracking LLM call results.

**Details:**

Create `src/resound/gateway/base.py` with:
1. `LLMResponse` dataclass using Python dataclasses (following existing codebase pattern with pydantic) containing: `content: str`, `model_used: str`, `tokens_in: int`, `tokens_out: int`, `cost_usd: float`, `latency_ms: float`, `raw_response: dict[str, Any]`
2. `LLMGateway` ABC with abstract method `complete(stage: str, prompt: str, response_schema: dict | None = None, temperature: float = 0.1, max_tokens: int = 1024) -> LLMResponse`
3. Define Literal type for stage: `'filter' | 'classify' | 'routing_tiebreaker' | 'memory_query'`
4. Add docstrings explaining the contract and expected usage patterns
<info added on 2026-05-02T11:41:48.071Z>
Design decisions to apply: (1) Use Pydantic BaseModel for LLMResponse, consistent with existing models in src/resound/models.py which uses Pydantic for all domain models (RawSignal, Classification, Route, FeedbackEvent). (2) Use plain str type for stage parameter instead of Literal to allow extensibility without code changes. (3) Use synchronous complete() method signature as the pipeline is serial today, with async support deferred to a future acomplete() method.
</info added on 2026-05-02T11:41:48.071Z>
<info added on 2026-05-02T13:17:57.614Z>
DESIGN LOCKED via grilling on 2026-05-02. Final implementation spec:

LLMResponse as Pydantic BaseModel (7 fields):
- content: str
- model_used: str (model that actually returned; may differ from stage primary if fallback fired)
- tokens_in: int
- tokens_out: int
- cost_usd: float | None (None when OpenRouter does not return usage.cost; no price-table fallback for demo)
- latency_ms: float
- raw_response: dict[str, Any]

Fields explicitly excluded from LLMResponse (belong to audit trail layer in Task 3): stage, attempts, prompt_hash, timestamp.

LLMGateway ABC complete() signature (simplified - NO temperature, NO max_tokens, NO model_override):

def complete(
    self,
    stage: str,
    prompt: str,
    response_schema: dict | None = None,
) -> LLMResponse

Design rationale: stage is plain str for extensibility. response_schema is flag-only sentinel for structured output requests. Gateway implementation owns model selection, retry, and fallback logic per models.yaml config for each stage. Follows existing Pydantic pattern in src/resound/models.py.
</info added on 2026-05-02T13:17:57.614Z>

### 1.2. Create models_config.py for loading and merging models.yaml

**Status:** done  
**Dependencies:** 1.1  

Implement configuration loading that merges global defaults from config/models.yaml with per-brand overrides from brands/<brand>/models.yaml.

**Details:**

Create `src/resound/gateway/models_config.py` with:
1. `StageConfig` dataclass with fields: `model: str`, `temperature: float`, `max_tokens: int`, `fallbacks: list[str]`
2. `ModelsConfig` dataclass containing a dict mapping stage names to StageConfig
3. `load_models_config(brand_slug: str | None = None, config_dir: Path | None = None, brands_dir: Path | None = None) -> ModelsConfig` function
4. Deep merge logic: brand-specific settings override global defaults at the field level
5. Follow existing yaml loading pattern from `resound/config.py` using `yaml.safe_load()`
6. Provide sensible defaults if no yaml files exist (using models from task description)
<info added on 2026-05-02T13:20:03.296Z>
Now I have sufficient context. Let me read the design_decisions.md for the complete spec and then formulate the update.Now I have the complete context. Let me formulate the update text for the subtask:

DESIGN LOCKED via grilling on 2026-05-02. Implementation spec for models_config.py:

File location: src/resound/gateway/models_config.py

StageConfig (Pydantic BaseModel, NOT dataclass) - exactly 5 fields:
- model: str
- temperature: float
- max_tokens: int
- fallbacks: list[str]
- timeout_s: float (per-stage wall-clock cap: filter ~5s, classify ~30s, others ~10s)

Excluded fields (out of demo scope): prompt_price, completion_price, provider_routing, system_prompt.

ModelsConfig: dict mapping stage name (str) to StageConfig. Implements get_stage_config(stage: str) -> StageConfig that raises LLMGatewayConfigError (imported from base.py) on unknown stage.

Function signature: load_models_config(brand_slug: str | None = None, config_dir: Path | None = None, brands_dir: Path | None = None) -> ModelsConfig

Config file locations:
- Global defaults: config/models.yaml
- Brand overrides: brands/<brand_slug>/models.yaml

Brand override merge semantics (LOCKED per design_decisions.md #16):
- FIELD-LEVEL merge over global defaults. Brand override file specifies only deltas; missing fields inherit from global.
- List fields (fallbacks) REPLACE the global list entirely - do NOT concat. Order matters in fallback chains.
- Merge happens at stage granularity: brand can override one stage without touching others.

YAML loading: Follow existing pattern from src/resound/config.py:37-65 using yaml.safe_load() with graceful fallback for missing files.

Sensible built-in defaults (no YAML required for tests): Use same model picks that subtask 1.6 will put in config/models.yaml (claude-sonnet-4-6 for classify, gpt-4.1-mini for filter/routing_tiebreaker/memory_query, with 1-element fallbacks for all stages).

File header comment must document precedence: "Brand overrides merge field-by-field over global defaults; list fields (fallbacks) replace; missing fields inherit."
</info added on 2026-05-02T13:20:03.296Z>

### 1.3. Implement OpenRouterGateway with retry and fallback logic

**Status:** done  
**Dependencies:** 1.1, 1.2  

Create the OpenRouter gateway implementation with exponential backoff retry for transient errors and fallback chain support for permanent errors.

**Details:**

Create `src/resound/gateway/openrouter.py` implementing `OpenRouterGateway(LLMGateway)`:
1. Initialize OpenAI client with `base_url='https://openrouter.ai/api/v1'` (pattern from existing `classifiers/openrouter.py`)
2. Set required headers: `HTTP-Referer`, `X-Title` (from env or defaults)
3. Accept `ModelsConfig` in constructor to get per-stage model settings
4. Implement retry logic with exponential backoff (base 2s, max 3 retries) for: 5xx errors, timeout errors, 429 rate limits
5. Implement fallback chain: on 4xx (non-429), try next model in stage's `fallbacks` list
6. Request JSON-mode (`response_format={'type': 'json_object'}`) when `response_schema` provided
7. Track timing with `time.perf_counter()` for latency_ms
8. Parse cost from `response.usage.cost` if available, else compute from tokens × model price lookup
<info added on 2026-05-02T13:22:12.066Z>
Based on my analysis of the codebase and the locked design decisions, I can now provide the update text for subtask 1.3.

DESIGN LOCKED via grilling on 2026-05-02. Implement OpenRouterGateway per the following final spec:

Constructor signature (testability lift - accept all four optionals, env-default the unset ones):

```python
def __init__(
    self,
    config: ModelsConfig,                  # required
    api_key: str | None = None,            # default: os.environ["OPENROUTER_API_KEY"]; raise LLMGatewayConfigError if missing
    http_referer: str | None = None,       # default: env OPENROUTER_APP_URL or "https://github.com/resound"
    app_title: str | None = None,          # default: env OPENROUTER_APP_NAME or "Resound"
    client: OpenAI | None = None,          # CRITICAL for testability - lets tests inject mock client without monkeypatching openai.OpenAI
)
```

Per-brand instance - one gateway per Pipeline. Pipeline wiring deferred to Task 9; do NOT touch src/resound/pipeline.py in this task.

Retry orchestration (LOCKED - both knobs matter):
- Per-model: max 3 attempts with exponential backoff (2s, 4s, 8s) on TRANSIENT errors only: 5xx, openai timeout exceptions (openai.APITimeoutError), 429 rate limits.
- Fallback chain: each fallback model gets a FRESH 3-attempt budget. Do not share the budget across the chain - point of fallbacks is to escape an outage on the primary provider.
- Per-stage wall-clock cap from StageConfig.timeout_s (filter ~5s, classify ~30s, others ~10s). Once exceeded, raise LLMGatewayTimeoutError even if retries/fallbacks remain. Use time.perf_counter() for timing.

Fallback trigger (NARROW - most 4xx are bugs, not fallback-able):
- TRIGGER fallback on: 404 (model not found), 422 (unprocessable), 413 (context too long), OpenRouter "no available provider" error.
- FATAL (raise immediately, no retry/fallback): 400 (bad request), 401 (auth), 403 (forbidden) - these are bugs to fix, not to fall back from.

JSON mode handling (try-and-detect with per-instance cache per design decision #6):
- First call with response_schema uses native JSON mode (response_format={"type": "json_object"}).
- On 400 error containing "response_format" or "json_object" in message, mark model in instance-level set _no_json_mode_models, retry once with prompt suffix "Respond with JSON only, no additional prose." + regex extraction.
- ALWAYS run regex extraction defensively r"\{.*\}" with re.DOTALL (pattern from existing classifiers/openrouter.py:69) even on JSON-mode success.

Cost handling (per design decision #7):
- Always include extra_body={"usage": {"include": true}} in API call.
- If response.usage.cost is present, use it for cost_usd.
- If missing, set cost_usd = None and log warning. No hardcoded price table for demo scope.

Exception hierarchy (per design decision #13):
- Import from base.py: LLMGatewayError (base), LLMGatewayConfigError, LLMGatewayAuthError, LLMGatewayExhaustedError(attempts: int), LLMGatewayTimeoutError, LLMGatewayParseError(raw_text: str).
- Config/Auth errors are FATAL - let them propagate.
- Exhausted/Timeout/Parse errors should be catchable via LLMGatewayError.

complete() implementation:
- Signature: complete(self, stage: str, prompt: str, response_schema: dict | None = None) -> LLMResponse
- Use self.config.get_stage_config(stage) to get StageConfig (raises LLMGatewayConfigError on unknown stage).
- Build model list: [stage_config.model] + stage_config.fallbacks
- Iterate models with fresh 3-attempt budget each, checking wall-clock timeout before each attempt.
- On success, return LLMResponse with model_used reflecting the actual model that succeeded (may be a fallback).
- On all models exhausted, raise LLMGatewayExhaustedError(attempts=total_attempts_made).

Reference existing pattern in src/resound/classifiers/openrouter.py:34-48 for OpenAI client initialization with base_url and default_headers. Use env() and require_env() helpers from src/resound/config.py:68-81.
</info added on 2026-05-02T13:22:12.066Z>

### 1.4. Add JSON extraction fallback for non-JSON-mode models

**Status:** done  
**Dependencies:** 1.3  

Implement fallback JSON extraction using prompt suffix and regex parsing for models that don't support native JSON mode.

**Details:**

Enhance `OpenRouterGateway` in `openrouter.py`:
1. Maintain a list/set of models known to NOT support JSON mode (e.g., some older/smaller models)
2. When `response_schema` is provided but model doesn't support JSON mode:
   - Append 'Respond with JSON only, no additional prose.' to the prompt
   - After response, use regex `r'\{.*\}'` with `re.DOTALL` to extract JSON (pattern from existing `classifiers/openrouter.py:69`)
3. Validate extracted JSON against provided `response_schema` if possible
4. Log warning when falling back to regex extraction
5. Raise clear error if no valid JSON found after fallback extraction
<info added on 2026-05-02T13:23:26.701Z>
Now I have a good understanding of the existing codebase structure, particularly the `classifiers/openrouter.py` file which shows the regex pattern at line 69. Let me generate the updated subtask details based on the user's design-locked specification.

DESIGN LOCKED via grilling on 2026-05-02. Implement JSON-mode fallback using TRY-AND-DETECT with per-process cache instead of a hardcoded blocklist.

Rationale: Hardcoded blocklists rot fast as OpenRouter's JSON-mode support matrix changes weekly. Try-and-detect costs one wasted request per new model per process, then never again.

Implementation algorithm for OpenRouterGateway in `src/resound/gateway/openrouter.py`:

1. Add per-instance cache: `self._no_json_mode_models: set[str] = set()`

2. When `complete()` called with `response_schema is not None`:
   a. If `self.model` already in `self._no_json_mode_models` -> skip native JSON mode, go directly to step 4
   b. Otherwise: send request with `response_format={"type": "json_object"}`

3. On 400 response containing "response_format" or "json_object" in the error message:
   a. Log warning: `f"{model} does not support JSON mode; caching and retrying with prompt-based fallback"`
   b. Add model to `self._no_json_mode_models`
   c. Fall through to step 4

4. Prompt-based fallback (when JSON mode unavailable):
   a. Append to prompt: "Respond with JSON only, no additional prose."
   b. Send request WITHOUT `response_format`
   c. Extract JSON from response using regex `r'\{.*\}'` with `re.DOTALL` (pattern from existing `classifiers/openrouter.py:69`)
   d. Validate extracted JSON against `response_schema` if provided
   e. If no valid JSON found, raise clear error

5. Error handling:
   - Log warning when falling back to regex extraction
   - Raise `JSONExtractionError` (or similar) if no valid JSON found after fallback
</info added on 2026-05-02T13:23:26.701Z>

### 1.5. Create gateway __init__.py with public exports

**Status:** done  
**Dependencies:** 1.1, 1.2, 1.3, 1.4  

Create the gateway module's __init__.py file that exports all public interfaces for easy importing.

**Details:**

Create `src/resound/gateway/__init__.py` with:
1. Import and re-export `LLMGateway`, `LLMResponse` from `base.py`
2. Import and re-export `OpenRouterGateway` from `openrouter.py`
3. Import and re-export `load_models_config`, `StageConfig`, `ModelsConfig` from `models_config.py`
4. Define `__all__` list with all public exports
5. Add module-level docstring explaining the gateway abstraction purpose
6. Optionally add a `build_gateway()` factory function (similar to `build_classifier()` in `classifiers/__init__.py`) that returns default configured gateway
<info added on 2026-05-02T13:25:09.045Z>
Now I have the context on the existing `classifiers/__init__.py` pattern. Let me also check if there are any existing gateway-related files or exception patterns in the codebase.Now I have a complete understanding of the codebase structure and the design decisions. Let me check the design_decisions.md for additional context.Now I have all the context needed. Let me formulate the update text for subtask 1.5 based on the user request and the design decisions document.

DESIGN LOCKED via grilling on 2026-05-02. Implement gateway/__init__.py per the following final spec.

File location: src/resound/gateway/__init__.py

Module docstring: Gateway abstraction layer for all LLM calls. Centralizes model selection, retry logic with exponential backoff, fallback chains, and cost tracking through OpenRouter.

Public exports (__all__) - INCLUDE exception classes from subtask 1.1 per design decision #13 (callers need these to catch correctly):

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
    # Exceptions (per design #13 - hierarchy under LLMGatewayError)
    "LLMGatewayError",
    "LLMGatewayConfigError",
    "LLMGatewayAuthError",
    "LLMGatewayExhaustedError",
    "LLMGatewayTimeoutError",
    "LLMGatewayParseError",
]

Import structure:
from resound.gateway.base import (
    LLMGateway,
    LLMResponse,
    LLMGatewayError,
    LLMGatewayConfigError,
    LLMGatewayAuthError,
    LLMGatewayExhaustedError,
    LLMGatewayTimeoutError,
    LLMGatewayParseError,
)
from resound.gateway.openrouter import OpenRouterGateway
from resound.gateway.models_config import load_models_config, StageConfig, ModelsConfig

build_gateway() factory per design decision #19 - brand-aware one-liner:

def build_gateway(brand_slug: str) -> OpenRouterGateway:
    """Build an OpenRouterGateway configured for a specific brand.

    Loads models.yaml config with global defaults merged with brand-specific
    overrides from brands/<brand_slug>/models.yaml. This is the public API;
    use OpenRouterGateway(config=..., client=...) directly for tests.
    """
    return OpenRouterGateway(config=load_models_config(brand_slug))

Return type annotation is OpenRouterGateway (concrete), not LLMGateway (abstract), per design decision #19 - public API stays brand-shaped.

Reference pattern: src/resound/classifiers/__init__.py:13-27 for factory function style and docstring format.
</info added on 2026-05-02T13:25:09.045Z>

### 1.6. Create default config/models.yaml with global defaults

**Status:** done  
**Dependencies:** 1.2  

Create the default models.yaml configuration file with sensible defaults for all LLM stages including model selection, temperature, max tokens, and fallback chains.

**Details:**

Create `config/models.yaml` file with:
1. `defaults:` section containing configuration for each stage:
   - `filter:` model: openai/gpt-4.1-mini, temperature: 0.0, max_tokens: 64, fallbacks: [anthropic/claude-haiku-4-5, google/gemini-2.0-flash]
   - `classify:` model: anthropic/claude-sonnet-4-6, temperature: 0.1, max_tokens: 1024, fallbacks: [openai/gpt-4.1, google/gemini-2.5-pro]
   - `routing_tiebreaker:` model: openai/gpt-4.1-mini, temperature: 0.0, max_tokens: 128, fallbacks: []
   - `memory_query:` model: openai/gpt-4.1-mini, temperature: 0.0, max_tokens: 256, fallbacks: []
2. Add YAML comments explaining each stage's purpose and why specific models were chosen
3. Ensure config directory exists (create `config/` if needed)
<info added on 2026-05-02T13:26:54.963Z>
Based on my analysis of the codebase, I can see:
1. No `config/` directory exists yet at the project root
2. YAML config patterns are already established in `brands/*/` with proper commenting style
3. The existing `OpenRouterClassifier` in `src/resound/classifiers/openrouter.py` uses OpenRouter-namespaced model identifiers like `anthropic/claude-sonnet-4-5`
4. The `config.py` uses `yaml.safe_load()` for config loading
5. Brand-level override semantics already exist (brands can have their own routing.yaml, etc.)

Here is the subtask update content:

DESIGN LOCKED via grilling on 2026-05-02. Updated specification includes the timeout_s field (added to StageConfig in subtask 1.2) and adds 1-element fallbacks for all stages (was empty for routing_tiebreaker/memory_query in original plan).

Final config/models.yaml content to implement:

```yaml
# =============================================================================
# Resound LLM Model Configuration - Global Defaults
# =============================================================================
# Each stage uses a specific model tuned to its latency/cost/capability needs.
# These are DEMO-PROVISIONAL models - suitable for development and early demos;
# production deployments may tune these based on observed cost/latency/accuracy.
#
# Stage purposes:
#   filter           - Fast cheap triage: ~70% of signals rejected here (5s timeout)
#   classify         - Deep classification work: full taxonomy extraction (30s timeout)
#   routing_tiebreaker - LLM fallback when no rule matches + low confidence (10s timeout)
#   memory_query     - Natural language -> structured filter translation (10s timeout)
#
# Brand override semantics: Brand-specific models.yaml files in brands/<slug>/
# can override any stage configuration. Brand configs are merged on top of these
# defaults, allowing per-brand model selection, temperature tuning, or fallback chains.
# =============================================================================

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
      - anthropic/claude-haiku-4-5   # Added for OpenAI hiccup insurance

  memory_query:
    model: openai/gpt-4.1-mini
    temperature: 0.0
    max_tokens: 256
    timeout_s: 10
    fallbacks:
      - anthropic/claude-haiku-4-5   # Added for same reliability reasoning
```

Implementation notes:
- Create `config/` directory at project root (same level as `src/`, `brands/`)
- File path: `config/models.yaml`
- Uses OpenRouter-namespaced model identifiers consistent with existing `src/resound/classifiers/openrouter.py` patterns
- Gateway loader (subtask 1.4) must implement brand override merging: load `config/models.yaml` as defaults, then deep-merge any `brands/<slug>/models.yaml` on top
</info added on 2026-05-02T13:26:54.963Z>
