# Creates the 4 subtasks for Task 16 (Ridge brand configuration bundle) with
# locked design decisions from the 2026-05-07 grilling session baked into
# --details at creation time. Uses add-subtask (a pure structural CLI op, no
# AI subprocess) to avoid the spawn-claude problem we hit with update-subtask.
#
# RUN THIS FROM A SEPARATE TERMINAL (outside an active Claude Code session)
# in case any task-master CLI path still spawns child claude processes.
#
# Usage (from project root):
#   powershell -ExecutionPolicy Bypass -File .taskmaster/scripts/apply-task16-grilling.ps1
#
# NOT idempotent: re-running creates duplicate subtasks. Run exactly once.
# Verify with: task-master show 16
#
# Note: Task 16 is pure configuration work -- no code changes. Bundle is fully
# specified by decisions #45-#56 in docs/design_decisions.md. No code or tests
# need modification. Ridge inherits global model defaults (no models.yaml file).
#
# Authoritative spec: docs/design_decisions.md (Task 16 section, decisions #45-#56).

$ErrorActionPreference = 'Stop'

# ----------------------------------------------------------------------------
# Subtask 16.1 -- Create directory + structural files (brand, sources, people, views)
# ----------------------------------------------------------------------------

$title_16_1 = 'Create brands/ridge/ directory and write 4 structural files (brand, sources, people, views)'

$desc_16_1 = 'Create the Ridge bundle directory and write the four mechanical-mirror YAML files. brand.yaml + sources.yaml + people.yaml + views.yaml all per the locked spec. No models.yaml file (per #53 -- Ridge inherits global defaults).'

$details_16_1 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #45, #46, #47, #52, #53, #55).

Create the directory:
  mkdir brands/ridge

Then write these 4 files exactly as specified.

==============================================================================
FILE 1: brands/ridge/brand.yaml (per #52)
==============================================================================

name: "Ridge"
description: "Minimalist wallets, rings, knives, and EDC accessories. DTC-first, lifetime warranty as load-bearing brand claim."
website: "https://ridge.com"
primary_contacts:
  - name: "Operator"
    role: "Resound admin"
    email: "ops@example.com"

==============================================================================
FILE 2: brands/ridge/sources.yaml (per #47)
==============================================================================

reddit:
  enabled: true
  subreddits:
    - ridge
    - EDC
    - wallets
  search_terms:
    - "ridge wallet"
    - "the ridge"
    - "ridge ring"
  limit: 25

g2:
  enabled: false  # Ridge is a consumer DTC brand; B2B review platform is not relevant.
  product_slug: ""

twitter:
  enabled: false  # Disabled in v1 per PRD-demo §5.2; bearer token integration deferred.
  handles:
    - "@RidgeWallets"
  search_terms:
    - "ridge wallet"
  limit: 50

==============================================================================
FILE 3: brands/ridge/people.yaml (per #55)
==============================================================================

# Ridge owner identities. These are placeholders -- on real deployment,
# brand operators populate Slack user IDs and email routing addresses
# with their actual team. The pipeline does not validate Slack handles;
# the strings just appear in the routing audit log and dashboard.

people:
  "@billing-lead":
    name: "Billing Lead"
    slack: "@U01BILLING"
    email: "billing@example.com"
  "@distribution-lead":
    name: "Distribution Lead"
    slack: "@U01DIST"
    email: "distribution@example.com"
  "@product-lead":
    name: "Product Lead"
    slack: "@U01PRODUCT"
    email: "product@example.com"

channels:
  "#triage":
    slack_channel: "#resound-triage"
    description: "Default landing zone for routed signals."
  "#exec":
    slack_channel: "#exec"
    description: "Exec + leadership. Critical / PR-grade signals only -- counterfeit incidents, mass warranty failures."
  "#cs-team":
    slack_channel: "#cs-incoming"
    description: "Customer service queue. Warranty claims and damaged shipments -- the high-volume Ridge bucket given lifetime warranty."
  "#eng-bugs":
    slack_channel: "#eng-bugs"
    description: "Engineering bug triage (website, checkout, app)."
  "#marketing-watch":
    slack_channel: "#marketing-watch"
    description: "Marketing FYI feed (campaigns, YouTube ambassador partnerships, PR)."
  "#review-queue":
    slack_channel: "#resound-review"
    description: "Low-confidence signals for human review before routing."

==============================================================================
FILE 4: brands/ridge/views.yaml (per #55)
==============================================================================

saved_views:
  - name: "Critical this week"
    filters:
      severity: ["critical"]
    period_days: 7
  - name: "Warranty escalations"
    filters:
      area: ["cs"]
      subarea: ["warranty_claims"]
    period_days: 30
  - name: "Durability complaints"
    filters:
      area: ["product"]
    period_days: 14

alert_thresholds:
  critical_per_day: 3        # if more than 3 critical signals in 24h, page exec
  area_spike_factor: 3.0     # if any area is 3x its 7-day average, alert

==============================================================================
CRITICAL CONSTRAINTS:
==============================================================================

1. Do NOT create brands/ridge/models.yaml. Per #53, the absence is intentional --
   it demonstrates the inheritance side of the field-level merge story.
   Liquid Death's bundle has the override; Ridge's bundle has the absence.
   Together they prove both sides of the merge.

2. Do NOT add a 4th saved view to views.yaml. Per #55, asymmetry with
   Liquid Death's 3-view bundle breaks the "Mirror with localized vocabulary"
   posture from #46.

3. Do NOT change the alert_thresholds numerics. Per #55, fabricated tuning
   without measurement is dishonest. Threshold tuning belongs to post-deployment
   measurement, not demo-time differentiation.

4. The placeholder header comment on people.yaml is REQUIRED per #55. It
   acknowledges that owner identities are deployment-time substitutions, not
   real Ridge team data -- honest about being a demo bundle.

5. views.yaml subarea filter "warranty_claims" (snake_case) MUST match the
   subarea string emitted by the classifier per #56. Section 3 + section 5 of
   understanding.md (subtask 16.2) must use the same snake_case form.

Acceptance criteria:
- brands/ridge/ directory exists.
- All 4 YAML files exist and parse cleanly via yaml.safe_load().
- brands/ridge/models.yaml does NOT exist.
- people.yaml has 3 people entries and 6 channel entries.
- views.yaml has exactly 3 saved_views entries.
- routing.yaml does not exist yet (subtask 16.3 creates it).
- understanding.md does not exist yet (subtask 16.2 creates it).
- No # TODO / # FIXME strings in any file (other than the placeholder-acknowledging
  header on people.yaml, which is documentation, not a TODO).
'@

# ----------------------------------------------------------------------------
# Subtask 16.2 -- Write understanding.md (the substantive content)
# ----------------------------------------------------------------------------

$title_16_2 = 'Write brands/ridge/understanding.md (6 sections, ~60 lines, 4 examples)'

$desc_16_2 = 'Substantive Ridge-specific content for sections 1-6. Drives classification quality. Highest-leverage file in the bundle.'

$details_16_2 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #48, #49, #50, #51, #52, #56).

Write the file at brands/ridge/understanding.md exactly as below. ~60 lines, 6 sections.

CRITICAL: All subarea strings in section 3 and the Classification specs in
section 5 use snake_case (warranty_claims, card_ejection_mechanism, ring_returns,
material_variants, etc.) per #56 -- they MUST match views.yaml filter strings
exactly. The classifier emits free-form subarea strings; if section 3 says
"warranty claims" with a space and views.yaml filters on "warranty_claims" with
underscore, the saved view will silently render empty.

==============================================================================
FILE: brands/ridge/understanding.md
==============================================================================

# Ridge -- brand context for Resound

## What we sell

Wallets (cardholder, leather, aluminum, titanium), rings, knives, and EDC
accessories. DTC-first via ridge.com; Amazon and limited brick-and-mortar
retail. Lifetime warranty on flagship products is a load-bearing brand claim
referenced in product pages, marketing, and customer expectations.

## Voice & positioning

Minimalist, durable, "buy once, cry once" product philosophy. Customer base
skews male, design-conscious, EDC-enthusiast (especially on Reddit's r/EDC
and r/wallets). The brand promise of lifetime durability creates a customer
base that takes product failures personally -- durability complaints generate
stronger emotional reactions than for typical consumer goods. Calibrate
severity accordingly: a "my wallet broke" post here is closer in weight to
"my software service had data loss" than to "my snack tasted weird."

## Functional area taxonomy

Use the standard Resound areas with these brand-specific subareas:

- **product**: build_quality, card_ejection_mechanism, RFID_blocking_concerns,
  material_variants (aluminum / titanium / leather), ring_sizing,
  durability_after_long_term_wear, new_skus
- **engineering**: website, DTC_checkout, mobile_app
- **billing**: refunds, charge_disputes, Ridge_subscription_billing
- **cs**: warranty_claims (high volume -- lifetime warranty exercise),
  order_status, ring_returns, damaged_shipments, missing_items
- **marketing**: brand_campaigns, YouTube_creator_partnerships, PR
- **ops**: retail_availability, distribution_gaps
  (mostly DTC -- lower volume than retail-heavy brands)
- **other**: EDC_fandom, gift_inquiries, off_topic_brand_name_mentions
  (e.g. mountain ridges, anatomical ridges)

## Glossary of brand-specific terms

- **"The Ridge"** (capitalized) -- Ridge's flagship wallet. A bare lowercase
  "ridge" mention without this branding may be off-topic (geology, anatomy,
  architecture).
- **"Basecamp"** -- Ridge's knife and tool product line (e.g. "The Basecamp
  Knife"); distinct from the wallet. Subarea routing differs.
- **"Buy it for life" / "lifetime guarantee"** -- Ridge's load-bearing brand
  promise. When customers invoke this, treat as `cs > warranty_claims` not
  generic product complaint, even if the surface complaint is about durability.
- **"Ridge+"** -- Ridge's wallet-protection subscription program. Billing issues
  here go to `billing > Ridge_subscription_billing`, distinct from one-time
  purchase refunds.

## Examples for reference

### Example 1 -- Genuine product complaint (route)
> "Got my Ridge wallet 6 months ago and the cards eject smoothly the first
> few weeks, but now I have to fight to get them out. Anyone else seeing this?"

Classification: is_about_brand=true, area=product, subarea=card_ejection_mechanism,
severity=medium, action_class=sprint, sentiment=negative.

### Example 2 -- Warranty claim (route)
> "My Ridge wallet's hinge broke after 18 months. Trying to claim the lifetime
> guarantee -- has anyone gone through this process? How long does it take?"

Classification: is_about_brand=true, area=cs, subarea=warranty_claims,
severity=medium, action_class=sprint, sentiment=neutral.
Note: "lifetime guarantee" trigger (per glossary) routes to cs > warranty_claims,
not product defect.

### Example 3 -- Brand fandom (FYI, do not over-route)
> "Five years on my Ridge wallet and still going strong. Honestly the only
> EDC purchase that was worth the hype. Buy once, cry once."

Classification: is_about_brand=true, area=marketing, severity=low,
action_class=fyi, sentiment=positive.

### Example 4 -- False positive (ignore)
> "The ridge on my Bellroy wallet is starting to wear down at the edge.
> Anyone know if they replace under warranty?"

Classification: is_about_brand=false, action_class=ignore.
Note: "the ridge" used as a feature description on a different brand's product
-- not a Ridge-the-brand mention. Glossary entry #1 disambiguates.

## Severity guidance

- **critical** -- viral PR risk, knife-product safety incident, mass warranty
  failure cluster, counterfeit-product mass exposure.
- **high** -- repeat issue across multiple customers, churn-risk Ridge+
  subscriber, warranty fulfillment delays at scale.
- **medium** -- single concrete complaint that needs a response.
- **low** -- minor opinion, edge case, easily resolved via existing docs.

==============================================================================
CRITICAL CONSTRAINTS:
==============================================================================

1. Subarea strings (warranty_claims, card_ejection_mechanism, etc.) use
   snake_case THROUGHOUT both section 3 (taxonomy) and section 5 (example
   classifications). This is per #56. Failure mode if violated: classifier
   emits "warranty claims" (space) but views.yaml filters on "warranty_claims"
   (underscore) -> saved view "Warranty escalations" silently renders empty
   on demo day.

2. Section 5 examples 2 and 4 MUST include their explicit Note: lines
   cross-referencing the glossary entries. Per #51, these notes make the file
   self-documenting -- the classifier sees the trigger language; human readers
   see the integration with section 4.

3. Section 2 (Voice & positioning) MUST include the "durability emotional"
   severity calibration hint per #52. Without it, section 2 reads as filler;
   classifier loses the cue that Ridge customers' product-failure posts carry
   higher severity weight than typical consumer goods complaints.

4. Section 6 (Severity guidance) critical triggers are Ridge-specific per #52:
   knife-product safety incidents, mass warranty failure clusters, counterfeit-
   product mass exposure. Do NOT copy Liquid Death's "food safety claim" -- it
   does not apply.

5. Total file should be ~60 lines (parity with brands/liquiddeath/understanding.md
   per #48). Going substantially shorter (<40 lines) creates visible asymmetry
   between bundles. Going substantially longer (>90 lines) has diminishing
   returns.

6. brand.yaml.description (subtask 16.1) carries a "lifetime warranty as load-
   bearing brand claim" tail. This redundancy with section 1 is intentional
   per #52 -- brand.yaml.description gets passed to classifier as part of
   brand_context; section 1 reinforces from a different surface.

Acceptance criteria:
- brands/ridge/understanding.md exists.
- File is ~60 lines (parity with brands/liquiddeath/understanding.md).
- > 500 chars (easily satisfied).
- All 6 sections present in the order: What we sell, Voice & positioning,
  Functional area taxonomy, Glossary, Examples for reference, Severity guidance.
- Section 5 has exactly 4 examples covering route / route / FYI / false-positive.
- All subarea strings use snake_case.
- "warranty_claims" appears in both section 3 list and section 5 example 2's
  Classification line -- exact-match for views.yaml filter.
- "card_ejection_mechanism" appears in both section 3 list and section 5
  example 1's Classification line.
- No # TODO / # FIXME placeholder strings.
'@

# ----------------------------------------------------------------------------
# Subtask 16.3 -- Write routing.yaml (the 8 rules)
# ----------------------------------------------------------------------------

$title_16_3 = 'Write brands/ridge/routing.yaml with 8 rules (2 renames + 1 swap from Liquid Death pattern)'

$desc_16_3 = '8-rule routing config. Two renames (cs_damaged_shipment -> cs_warranty_or_damage; ops_retail_availability -> ops_distribution_gripes). One swap (product_roadmap_input -> product_durability_complaint). All route_to handles must exist in people.yaml.'

$details_16_3 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #54).

Write brands/ridge/routing.yaml exactly as below. 8 rules. Verify all route_to
handles exist in people.yaml (subtask 16.1 created the required entries).

==============================================================================
FILE: brands/ridge/routing.yaml
==============================================================================

default_route: "#triage"

rules:
  - name: "critical_pr_risk"
    when:
      severity: "critical"
    route_to: "#exec"
    priority: "immediate"
    notes: "Anything critical -- exec/comms triages first. Ridge counterfeit incidents and mass warranty failures both land here."

  - name: "billing_high"
    when:
      area: "billing"
      severity: ">=high"
    route_to: "@billing-lead"
    priority: "immediate"

  - name: "cs_warranty_or_damage"
    when:
      area: "cs"
      action_class: "sprint"
    route_to: "#cs-team"
    notes: "Warranty claims and damaged shipments both land here -- the high-volume CS bucket for Ridge given lifetime warranty. Renamed from Liquid Death's cs_damaged_shipment."

  - name: "ops_distribution_gripes"
    when:
      area: "ops"
    route_to: "@distribution-lead"
    notes: "Renamed from Liquid Death's ops_retail_availability -- Ridge is mostly DTC; lower volume but pattern persists."

  - name: "product_durability_complaint"
    when:
      area: "product"
      severity: ">=medium"
    route_to: "@product-lead"
    notes: "Ridge's high-volume product pattern is durability complaints (card ejection mechanism, ring sizing, material wear), not feature-roadmap input. Replaces Liquid Death's product_roadmap_input."

  - name: "engineering_bugs"
    when:
      area: "engineering"
      severity: ">=medium"
    route_to: "#eng-bugs"

  - name: "marketing_fyi"
    when:
      area: "marketing"
    route_to: "#marketing-watch"

  - name: "low_confidence_review_queue"
    when:
      confidence: "<0.5"
    route_to: "#review-queue"
    notes: "Classifier was unsure -- human reviews before routing."

==============================================================================
CRITICAL CONSTRAINTS:
==============================================================================

1. Exactly 8 rules. Adding a 9th (e.g. keeping product_roadmap_input alongside
   product_durability_complaint) breaks parity with Liquid Death per #54.
   Removing one breaks the architecture (medium-severity product complaints
   would fall to default route, defeating automated routing).

2. Three owner identity renames cascade from people.yaml (subtask 16.1):
   - #exec-pr -> #exec
   - @retail-ops -> @distribution-lead
   - @product-pm -> @product-lead
   Verify each route_to handle in this file matches an entry in people.yaml.
   The router refuses to dispatch to undefined identities.

3. The notes: fields on cs_warranty_or_damage, ops_distribution_gripes, and
   product_durability_complaint MUST cross-reference Liquid Death's analogues
   per #54. This makes the bundle relationship self-documenting for any
   reviewer comparing the two routing.yaml files.

4. Do NOT add a separate rule for warranty_claims subarea routing within cs.
   The cs_warranty_or_damage rule fires on action_class=sprint regardless of
   subarea, which catches both warranty claims and damaged shipments. The
   subarea distinction is preserved in classifications/llm_calls tables for
   dashboard saved-view filtering.

5. product_durability_complaint fires on severity>=medium, NOT on
   action_class=sprint. This is intentional -- Ridge customers post durability
   complaints across multiple action_class values (sprint, fyi, ignore depending
   on tone), and severity is the better gate for "is this product team's
   problem."

Acceptance criteria:
- brands/ridge/routing.yaml exists and parses via yaml.safe_load().
- Exactly 8 rules, in the exact order shown above (critical_pr_risk first,
  low_confidence_review_queue last).
- default_route is "#triage".
- All route_to handles match entries in brands/ridge/people.yaml:
  #exec, @billing-lead, #cs-team, @distribution-lead, @product-lead,
  #eng-bugs, #marketing-watch, #review-queue, #triage.
- No reference to #exec-pr, @retail-ops, or @product-pm (Liquid Death's identities).
- product_roadmap_input rule is NOT present (replaced by product_durability_complaint).
'@

# ----------------------------------------------------------------------------
# Subtask 16.4 -- Three-layer verification + fix any string mismatches
# ----------------------------------------------------------------------------

$title_16_4 = 'Three-layer verification: static + healthcheck + functional poll-once run'

$desc_16_4 = 'Verify the bundle works end-to-end. Static checks (files exist + parse). Healthcheck reports correct counts. Functional run ingests + classifies + routes at least one real Reddit signal. Fix any subarea string mismatches surfaced.'

$details_16_4 = @'
DESIGN LOCKED via grilling on 2026-05-07 (see docs/design_decisions.md #56).

Run all three verification layers in order. Each must pass before "done."

==============================================================================
LAYER 1 -- Static verification
==============================================================================

Run these checks (manually or via a small shell loop):

1. All 6 files exist:
   ls brands/ridge/{brand,sources,routing,people,views}.yaml brands/ridge/understanding.md

2. brands/ridge/models.yaml does NOT exist (per #53):
   if (Test-Path brands/ridge/models.yaml) { Write-Error "models.yaml should not exist" }

3. All YAML files parse:
   python -c "import yaml; [yaml.safe_load(open(f'brands/ridge/{n}.yaml')) for n in ['brand','sources','routing','people','views']]"

4. understanding.md > 500 chars:
   (Get-Item brands/ridge/understanding.md).Length  # should be ~2000+

5. No # TODO / # FIXME outside placeholder header:
   Select-String -Path brands/ridge/* -Pattern "# TODO|# FIXME" |
     Where-Object { $_.Line -notmatch "placeholder" }
   # should return nothing

==============================================================================
LAYER 2 -- Healthcheck verification
==============================================================================

Run:
  resound healthcheck --brand ridge

Expected output (post-Task-9 #44 format):
  Ridge (ridge)
    description: Minimalist wallets, rings, knives, and EDC accessories...
    sources configured: ['reddit']
    routing rules: 8
    people entries: 3
    channel entries: 6
    understanding doc: ~2000 chars
    classify model: anthropic/claude-sonnet-4-6
      source: config/models.yaml (global default)
      fallbacks: openai/gpt-4.1, google/gemini-2.5-pro
      timeout: 30s
    [x] OPENROUTER_API_KEY set

Pre-Task-9 (current state if Task 9 hasn't shipped):
  classifier provider line + classifier model line will appear instead of the
  4-line classify model block. Verify the brand context counts (8 rules,
  3 people, 6 channels) regardless of classifier display format.

CRITICAL pre-conditions:
- OPENROUTER_API_KEY must be set in .env or environment.
- REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT must be set.
- Resound must be installed: pip install -e . from project root.

Failures to debug:
- "Brand directory not found" -> subtask 16.1 didn't create brands/ridge/.
- "Routing rule count mismatch" -> routing.yaml has wrong number of entries.
- "channel '#exec-pr' undefined" -> routing.yaml references Liquid Death's
  channel; should be '#exec' per #54.

==============================================================================
LAYER 3 -- Functional verification
==============================================================================

Run:
  resound poll-once --brand ridge

Expected output:
  Resound running once for Ridge...
  polled    25 (or however many returned)
  new       N (where N >= 1; first run typically returns multiple)
  classified N
  routed    M (where M may be < N if some classify as ignored_by_classifier)
  ignored   K (false positives + low-relevance)
  errors    0

Then verify rows in the database:
  python -c "from resound.memory import SqlMemory; m = SqlMemory(); print(m.query_recent('ridge', limit=5))"

Should return at least 1 signal with brand_slug='ridge'.

Open the dashboard to visually verify:
  resound dashboard --brand ridge

Live feed tab should show Ridge signals with their classifications.
"Warranty escalations" saved view should populate IF a warranty_claims signal
appeared (depends on what Reddit returned).

==============================================================================
FAILURE MODES TO DEBUG (per #56)
==============================================================================

If functional run reveals issues, here are the most common failure modes:

1. **Saved-view subarea string mismatch (HIGHEST RISK per #56):**
   - Symptom: "Warranty escalations" saved view in dashboard renders empty
     even when signals tagged with warranty subarea exist.
   - Root cause: classifier emitted "warranty claims" (with space) instead of
     "warranty_claims" (with underscore).
   - Fix: verify subtask 16.2's understanding.md uses snake_case throughout.
     If the classifier still emits the wrong form, add a more explicit gloss
     to section 3 like: "warranty_claims (use this exact snake_case form when
     classifying)".

2. **Routing rule reference to undefined channel:**
   - Symptom: healthcheck or poll-once raises an error like
     "channel '@retail-ops' not in people.yaml".
   - Root cause: routing.yaml has Liquid Death's channel name; people.yaml
     has Ridge's renamed identity.
   - Fix: verify the three renames per #54 in subtask 16.3.

3. **Search terms returning zero signals:**
   - Symptom: poll-once returns "polled 0".
   - Root cause: r/EDC/r/wallets had no recent posts matching "ridge wallet" /
     "the ridge" / "ridge ring" -- unusual but possible on low-traffic days.
   - Fix: NOT a bundle bug. Wait a few hours and re-run, OR temporarily
     broaden search terms for testing only (do not commit broader terms).

4. **Reddit API rate limit:**
   - Symptom: poll-once raises an exception about Reddit rate limiting.
   - Root cause: too many runs in quick succession.
   - Fix: wait 1-2 minutes between runs.

5. **Classifier returning stub fallbacks:**
   - Symptom: many signals have summary="[classifier fallback: ...]" and
     action_class=ignore.
   - Root cause: OpenRouter API key invalid OR classify model unavailable OR
     prompt rejected by model.
   - Fix: verify OPENROUTER_API_KEY is correct; check OpenRouter dashboard
     for the configured classify model availability; check logs for the
     specific error.

==============================================================================
ACCEPTANCE CRITERIA -- all three layers must pass:
==============================================================================

Layer 1 (Static):
  [ ] All 5 YAML files + understanding.md exist at brands/ridge/.
  [ ] brands/ridge/models.yaml does NOT exist.
  [ ] All YAML parses cleanly via yaml.safe_load.
  [ ] understanding.md > 500 chars.
  [ ] No # TODO / # FIXME outside the people.yaml placeholder header.

Layer 2 (Healthcheck):
  [ ] `resound healthcheck --brand ridge` exits 0.
  [ ] Output reports: name "Ridge", reddit enabled, 8 routing rules,
    3 people entries, 6 channel entries, understanding doc length.
  [ ] Classify model reports global default OR brand-context model;
    OPENROUTER_API_KEY check passes.

Layer 3 (Functional):
  [ ] `resound poll-once --brand ridge` exits 0.
  [ ] At least 1 row in signals table with brand_slug='ridge'.
  [ ] At least 1 row in classifications table joined to a Ridge signal.
  [ ] At least 1 row in routes table joined to a Ridge classification.
  [ ] `resound dashboard --brand ridge` opens; live feed renders Ridge signals.
  [ ] Saved view filter strings (views.yaml) match classifier subarea output.
'@

# ----------------------------------------------------------------------------
# Execute
# ----------------------------------------------------------------------------

$subtasks = @(
    @{ title = $title_16_1; description = $desc_16_1; details = $details_16_1 },
    @{ title = $title_16_2; description = $desc_16_2; details = $details_16_2 },
    @{ title = $title_16_3; description = $desc_16_3; details = $details_16_3 },
    @{ title = $title_16_4; description = $desc_16_4; details = $details_16_4 }
)

$index = 0
foreach ($s in $subtasks) {
    $index++
    Write-Host "==> Creating subtask 16.$index : $($s.title)" -ForegroundColor Cyan
    task-master add-subtask `
        --parent=16 `
        --title=$($s.title) `
        --description=$($s.description) `
        --details=$($s.details)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED creating subtask 16.$index (exit $LASTEXITCODE). Stopping." -ForegroundColor Red
        Write-Host "If --details is not a recognized flag in your task-master version, edit this script" -ForegroundColor Yellow
        Write-Host "to drop --details and re-run, then use update-subtask separately to add the design notes." -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "All 4 subtasks created. Verify with: task-master show 16" -ForegroundColor Green
Write-Host "Authoritative design spec: docs/design_decisions.md (Task 16 section, decisions #45-#56)" -ForegroundColor Gray
