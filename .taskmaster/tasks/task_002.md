# Task ID: 2

**Title:** Add models.yaml Configuration Schema

**Status:** done

**Dependencies:** 1 ✓

**Priority:** high

**Description:** Create the models.yaml configuration file schema and example files for per-stage model selection with fallback chains.

**Details:**

1. Create `config/models.yaml` with global defaults:
```yaml
defaults:
  filter:
    model: openai/gpt-4.1-mini
    temperature: 0.0
    max_tokens: 64
    fallbacks: [anthropic/claude-haiku-4-5, google/gemini-2.0-flash]
  classify:
    model: anthropic/claude-sonnet-4-6
    temperature: 0.1
    max_tokens: 1024
    fallbacks: [openai/gpt-4.1, google/gemini-2.5-pro]
  routing_tiebreaker:
    model: openai/gpt-4.1-mini
    temperature: 0.0
    max_tokens: 128
    fallbacks: []
  memory_query:
    model: openai/gpt-4.1-mini
    temperature: 0.2
    max_tokens: 512
    fallbacks: []
```

2. Create `brands/liquiddeath/models.yaml` with optional overrides:
```yaml
brand_overrides:
  liquiddeath:
    classify:
      model: anthropic/claude-sonnet-4-5
```

3. Update `BrandConfig` in `src/resound/config.py`:
   - Add `models: dict[str, Any]` field
   - Load `models.yaml` from brand directory if exists
   - Add method `get_model_config(stage: str) -> StageConfig` that merges global + brand overrides

4. Update `.env.example` to document that `RESOUND_CLASSIFIER_MODEL` and `RESOUND_FILTER_MODEL` are deprecated in favor of models.yaml

**Test Strategy:**

Test models.yaml loading:
- Test global defaults load correctly when no brand override exists
- Test brand overrides merge correctly with global defaults
- Test missing models.yaml uses sensible defaults
- Test invalid YAML raises clear error message
- Test `get_model_config()` returns correct merged config per stage

## Subtasks

### 2.1. Create brands/liquiddeath/models.yaml as single-field classify.model override

**Status:** done  
**Dependencies:** None  

Add the brand-side example file demonstrating the field-level merge. This file is the on-camera artifact for the demo model swap (Tasks 21, 25).

**Details:**

DESIGN LOCKED via grilling on 2026-05-03 (see docs/design_decisions.md #22).

File path: brands/liquiddeath/models.yaml

Contents (single-field override â€” model name is DEMO-PROVISIONAL per #17):

# Brand-specific model overrides for Liquid Death.
# Field-level merge over config/models.yaml: only fields listed here
# override the global default; everything else (fallbacks, temperature,
# max_tokens, timeout_s) inherits.
#
# Why we override classify here: Liquid Death's brand voice is
# deliberately loud and sarcastic. The default classify model
# misreads ironic praise as genuine and snark as outage-level negative.
# Routing this brand to a stronger model materially improves precision
# on the action_class field. (Demo-provisional model name; revisit
# closer to demo per docs/design_decisions.md #17.)

classify:
  model: anthropic/claude-opus-4-7

CRITICAL constraints from the grilling:

1. Override exactly ONE field (classify.model). Do NOT override filter, routing_tiebreaker, memory_query, or any other classify field. The demo's field-level

### 2.2. Add docstring to BrandConfig documenting models.yaml + why no data field

**Status:** done  
**Dependencies:** None  

Update the BrandConfig docstring in src/resound/config.py to document where models config lives and explain the deliberate decision NOT to expose it as a data field.

**Details:**

DESIGN LOCKED via grilling on 2026-05-03 (see docs/design_decisions.md #24).

File: src/resound/config.py

Change: docstring update ONLY. Do NOT add a `models` field. Do NOT add a `get_model_config()` method. Do NOT touch load_brand_config().

Rationale (capture in the docstring): no current caller (Pipeline post-Task-9, CLI testing in Task 10) reads from brand.models. Adding the field would create a resound.config -> resound.gateway import edge that does not otherwise exist. A merged ModelsConfig would be inconsistent with the raw-dict shape of routing / people / views fields.

Suggested docstring (drop into BrandConfig at line 18):

    @dataclass
    class BrandConfig:
        "A

### 2.3. Update .env.example: deprecate RESOUND_CLASSIFIER_MODEL, delete RESOUND_FILTER_MODEL

**Status:** done  
**Dependencies:** None  

Surgically update .env.example to communicate the new models.yaml mechanism without prematurely breaking still-load-bearing env vars.

**Details:**

DESIGN LOCKED via grilling on 2026-05-03 (see docs/design_decisions.md #25).

File: .env.example

Three surgical edits, current state (lines 23-30):

    # Optional - model overrides
    # Use OpenRouter's namespaced format when provider=openrouter:
    #   anthropic/claude-sonnet-4-5, google/gemini-2.5-pro,
    #   deepseek/deepseek-chat, meta-llama/llama-3.3-70b-instruct, etc.
    # Use bare Claude IDs when provider=anthropic:
    #   claude-sonnet-4-6, claude-haiku-4-5-20251001
    RESOUND_CLASSIFIER_MODEL=anthropic/claude-sonnet-4-5
    RESOUND_FILTER_MODEL=meta-llama/llama-3.3-70b-instruct

Replace with:

    # Model selection lives in config/models.yaml (with optional per-brand
    # overrides in brands/<slug>/models.yaml). See docs/design_decisions.md
    # for the merge semantics.
    #
    # DEPRECATED - RESOUND_CLASSIFIER_MODEL is still read by the existing
    # classifier and will be removed once classifiers route through the
    # gateway (Task 9). New deployments should configure models.yaml
    # instead of setting this.
    # RESOUND_CLASSIFIER_MODEL=anthropic/claude-sonnet-4-5

CRITICAL constraints from the grilling:

1. DELETE RESOUND_FILTER_MODEL line outright. Do NOT label it deprecated. It was documented but NEVER read by any code (verified: grep RESOUND_FILTER_MODEL across src/ returns zero hits). Labeling pure cruft as deprecated is dishonest about what was ever live.

2. COMMENT OUT (do not delete) the RESOUND_CLASSIFIER_MODEL line. It is still genuinely live â€” read by classifiers/openrouter.py:45, classifiers/claude.py:31, cli.py:88. Commenting preserves discoverability for someone debugging why
