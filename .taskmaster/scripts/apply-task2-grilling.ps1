# Creates the 3 subtasks for Task 2 (rescoped to integration-only) with
# locked design decisions from the 2026-05-03 grilling session baked into
# --details at creation time. Uses add-subtask (a pure structural CLI op,
# no AI subprocess) to avoid the spawn-claude problem we hit with
# update-subtask.
#
# RUN THIS FROM A SEPARATE TERMINAL (outside an active Claude Code session)
# in case any task-master CLI path still spawns child claude processes.
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File .taskmaster/scripts/apply-task2-grilling.ps1
#
# NOT idempotent: re-running creates duplicate subtasks 2.4 / 2.5 / 2.6.
# Run exactly once. Verify with: task-master show 2
#
# Note on parent task description: Task 2's parent details still describe
# the original (pre-rescope) plan. We deliberately do NOT update it here
# because update-task uses AI and hits the same subprocess issue. The
# subtasks override the parent in practice — anyone reading Task 2 will
# follow the 3 subtask details, not the stale parent description.
# Authoritative spec: docs/design_decisions.md (Task 2 section).

$ErrorActionPreference = 'Stop'

# ----------------------------------------------------------------------------
# Subtask 2.1 — example brand override file (the on-camera demo artifact)
# ----------------------------------------------------------------------------

$title_2_1 = 'Create brands/liquiddeath/models.yaml as single-field classify.model override'

$desc_2_1 = 'Add the brand-side example file demonstrating the field-level merge. This file is the on-camera artifact for the demo model swap (Tasks 21, 25).'

$details_2_1 = @'
DESIGN LOCKED via grilling on 2026-05-03 (see docs/design_decisions.md #22).

File path: brands/liquiddeath/models.yaml

Contents (single-field override — model name is DEMO-PROVISIONAL per #17):

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

1. Override exactly ONE field (classify.model). Do NOT override filter, routing_tiebreaker, memory_query, or any other classify field. The demo's "field-level merge" point lands hardest when there is literally one line of override against a dozen lines of inherited config.

2. Top-level keys are STAGE NAMES (classify, filter, etc.). Do NOT nest under "brand_overrides:" or "brand_overrides.liquiddeath:". The path brands/liquiddeath/models.yaml already encodes the brand slug — nesting it inside the file is redundant and a footgun (someone could put fulfil overrides in the liquiddeath file).

3. The rationale comment is REQUIRED, not optional. It is what a reviewer reads on camera (Task 25 - Video Beat 3) and what tells future maintainers why this brand is the example.

4. Do NOT create brands/fulfil/models.yaml in this subtask (per #23). The absence of a file in fulfil is itself the demonstration that overrides are opt-in.

Acceptance criteria:
- File exists at brands/liquiddeath/models.yaml.
- File parses as valid YAML.
- Manual smoke check: load_models_config("liquiddeath") returns a ModelsConfig where classify.model == "anthropic/claude-opus-4-7" AND classify.temperature == 0.1 (inherited) AND classify.fallbacks == ["openai/gpt-4.1", "google/gemini-2.5-pro"] (inherited) AND classify.timeout_s == 30 (inherited). This validates the field-level merge from #16.
- No code changes in src/ for this subtask.
'@

# ----------------------------------------------------------------------------
# Subtask 2.2 — BrandConfig docstring (no data field changes)
# ----------------------------------------------------------------------------

$title_2_2 = 'Add docstring to BrandConfig documenting models.yaml + why no data field'

$desc_2_2 = 'Update the BrandConfig docstring in src/resound/config.py to document where models config lives and explain the deliberate decision NOT to expose it as a data field.'

$details_2_2 = @'
DESIGN LOCKED via grilling on 2026-05-03 (see docs/design_decisions.md #24).

File: src/resound/config.py

Change: docstring update ONLY. Do NOT add a `models` field. Do NOT add a `get_model_config()` method. Do NOT touch load_brand_config().

Rationale (capture in the docstring): no current caller (Pipeline post-Task-9, CLI testing in Task 10) reads from brand.models. Adding the field would create a resound.config -> resound.gateway import edge that does not otherwise exist. A merged ModelsConfig would be inconsistent with the raw-dict shape of routing / people / views fields.

Suggested docstring (drop into BrandConfig at line 18):

    @dataclass
    class BrandConfig:
        """A complete brand configuration bundle.

        Loaded from brands/<slug>/ which contains:
          - brand.yaml, sources.yaml, routing.yaml, people.yaml, views.yaml
          - understanding.md
          - (optional) models.yaml — per-stage model overrides

        models.yaml is deliberately NOT exposed as a field on this class.
        It is loaded separately by `resound.gateway.load_models_config(slug)`,
        which merges it field-by-field over the global defaults in
        config/models.yaml. Callers that need model config should call
        load_models_config(brand.slug) or build_gateway(brand.slug) directly.

        See docs/design_decisions.md #24 for the reasoning behind this split.
        """

CRITICAL constraints from the grilling:

1. Do NOT add `models: dict[str, Any]` to the dataclass fields.
2. Do NOT add `get_model_config(stage: str)` method.
3. Do NOT modify load_brand_config() to load models.yaml — the gateway loader owns that.
4. The docstring MUST mention that models.yaml is loaded by the gateway loader, so a developer reading this class knows where to look.

Acceptance criteria:
- BrandConfig docstring updated, no field/method changes.
- `mypy src/resound/config.py` (or equivalent type check) still passes.
- No new imports in config.py.
- All existing tests pass without modification.
'@

# ----------------------------------------------------------------------------
# Subtask 2.3 — .env.example surgical edits
# ----------------------------------------------------------------------------

$title_2_3 = 'Update .env.example: deprecate RESOUND_CLASSIFIER_MODEL, delete RESOUND_FILTER_MODEL'

$desc_2_3 = 'Surgically update .env.example to communicate the new models.yaml mechanism without prematurely breaking still-load-bearing env vars.'

$details_2_3 = @'
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

1. DELETE RESOUND_FILTER_MODEL line outright. Do NOT label it deprecated. It was documented but NEVER read by any code (verified: grep RESOUND_FILTER_MODEL across src/ returns zero hits). Labeling pure cruft as "deprecated" is dishonest about what was ever live.

2. COMMENT OUT (do not delete) the RESOUND_CLASSIFIER_MODEL line. It is still genuinely live — read by classifiers/openrouter.py:45, classifiers/claude.py:31, cli.py:88. Commenting preserves discoverability for someone debugging "why isn't my model env var taking effect."

3. LEAVE RESOUND_CLASSIFIER_PROVIDER UNTOUCHED (line 2). It is still load-bearing for the anthropic-vs-openrouter factory switch (classifiers/__init__.py:19). Task 9 should remove both the var and the factory in one motion — do NOT pre-announce that deprecation here.

Acceptance criteria:
- RESOUND_FILTER_MODEL line is gone.
- RESOUND_CLASSIFIER_MODEL is commented out with the deprecation note.
- RESOUND_CLASSIFIER_PROVIDER is unchanged at line 2.
- The Optional/OpenRouter format comment block (lines 23-28) is replaced with the new "models.yaml lives at..." comment block.
- File still loads via `dotenv` without errors.
- README.md:45 update is OUT OF SCOPE for this subtask (deferred to Task 14 / Task 18 per cross-task notes in docs/design_decisions.md).
'@

# ----------------------------------------------------------------------------
# Execute
# ----------------------------------------------------------------------------

$subtasks = @(
    @{ title = $title_2_1; description = $desc_2_1; details = $details_2_1 },
    @{ title = $title_2_2; description = $desc_2_2; details = $details_2_2 },
    @{ title = $title_2_3; description = $desc_2_3; details = $details_2_3 }
)

$index = 0
foreach ($s in $subtasks) {
    $index++
    Write-Host "==> Creating subtask 2.$index : $($s.title)" -ForegroundColor Cyan
    task-master add-subtask `
        --parent=2 `
        --title=$($s.title) `
        --description=$($s.description) `
        --details=$($s.details)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED creating subtask 2.$index (exit $LASTEXITCODE). Stopping." -ForegroundColor Red
        Write-Host "If --details is not a recognized flag in your task-master version, edit this script" -ForegroundColor Yellow
        Write-Host "to drop --details and re-run, then use update-subtask separately to add the design notes." -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "All 3 subtasks created. Verify with: task-master show 2" -ForegroundColor Green
Write-Host "Authoritative design spec: docs/design_decisions.md (Task 2 section, decisions #21-#25)" -ForegroundColor Gray
