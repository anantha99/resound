# Resound — Product Requirements Document

**Version:** 1.0 (v1 scope)
**Status:** Draft
**Last updated:** April 2026

---

## 1. Summary

Resound is a customer-signal intelligence layer that ingests every public touchpoint about a brand — reviews, social posts, forum discussions, support tickets — classifies and diagnoses each signal, and routes it to the single internal owner who can act on it. Every signal, route, and outcome is captured in an append-only memory layer that becomes the brand's living database of customer voice.

The thesis: voice-of-customer tools today are services brands rent. Their data, routing decisions, and outcomes don't accumulate as the brand's asset. Resound keeps everything inside the company. Five years in, a Resound deployment is a memory layer no competitor can replicate overnight.

The system is modular and brand-configurable. Six YAML/markdown files describe a brand's sources, taxonomy, routing rules, and org structure. Onboarding a new brand is a configuration task, not an engineering one.

## 2. Problem

Customer voice is scattered. A complaint about bundle accounting might land in a G2 review, a Trustpilot star, a Reddit thread, a support ticket, and an NPS free-text — five places, five owners, no shared memory, no closed loop.

The cost is invisible but huge. The same issue gets relitigated every quarter because nobody remembers it was solved last year. Engineering builds features that customer success already heard weren't wanted. Sales loses deals over objections that product would have addressed in a sprint had they known. Knowledge that should be a strategic asset stays trapped as tribal lore in individual heads.

Existing voice-of-customer tools (Anecdote, Enterpret, Medallia) help with aggregation but stop at dashboards. They don't route to the right person, they don't track whether the action got taken, they don't close the loop, and the resulting database belongs to the vendor — not the brand.

## 3. Goals

**v1 goals (3 weekends, end of week 3):**

- Ingest signals from at least three public sources (Reddit, G2, Twitter/X) for one configured brand.
- Classify each signal by functional area, severity, and required action class using Claude.
- Route each signal to the correct internal owner via a configurable rules engine.
- Persist every signal, classification, route, and feedback event in an append-only memory layer.
- Provide a dashboard showing the live signal feed, the memory browser, and the routing audit log.
- Demonstrate end-to-end onboarding of a new brand by editing six configuration files only — no code changes.

**Non-goals for v1 (explicit deferrals):**

- Learned/ML-based routing — v1 uses LLM + rules, learning loop is captured but not yet acted on.
- Private channel ingestion (support tickets, Gong calls, Zendesk) — these need per-customer integrations and are v2.
- Multi-language signals — English only.
- Action automation — humans take action, system tracks the outcome.
- SLA management or escalation chains — v2.
- Customer-facing portal where merchants see their own routed signals — v3.

## 4. Users

**Primary user (operator):** Internal product/engineering/CX leader at the deployed brand. They configure routing rules, monitor the signal feed, intervene when routing is wrong, and use the memory layer for retrospectives and roadmap planning.

**Secondary user (recipient):** The individual employee Resound routes a signal to. Receives a notification (file-based in v1, Slack/email later), acts on the signal, and provides feedback (right person? wrong person?) so the system learns.

**Tertiary user (strategic):** Founder/CEO using the memory layer as a quarterly input — what's our customer actually saying, what changed, what stopped showing up.

## 5. Architecture

Five modular layers. Each layer defines an interface; concrete implementations are pluggable per brand. Configuration determines which implementations are active.

### 5.1 Layer 1 — Ingestion

**Responsibility:** Pull raw signals from external surfaces. Normalize to a common schema. Dedupe.

**Interface:** `SourceAdapter` ABC with methods `poll() -> list[RawSignal]`, `name`, `dedupe_key(signal)`.

**v1 implementations:**

- `RedditSource` — uses PRAW, polls configured subreddits and brand-name search.
- `G2Source` — stub for v1; full impl in week 2.
- `TwitterSource` — stub for v1; full impl in week 2.

**Common schema (`RawSignal`):** source, external_id, url, author_handle, content, posted_at, raw_metadata.

**Configuration:** `brands/<brand>/sources.yaml` lists active adapters and parameters. Credentials live in `.env`, never in the brand config.

### 5.2 Layer 2 — Understanding

**Responsibility:** For each raw signal, decide if it's relevant, what it's about, how serious it is, what action class it warrants.

**Interface:** `Classifier` ABC with method `classify(raw: RawSignal, brand_context: str) -> Classification`.

**v1 implementation:** `ClaudeClassifier` — single Anthropic API call per signal with structured JSON output. Brand-specific context (taxonomy, glossary, examples) is injected from `brands/<brand>/understanding.md`.

**`Classification` schema:**
- `is_about_brand` (bool) — filter for false positives.
- `area` (string) — functional area: product, engineering, billing, cs, marketing, ops, other.
- `subarea` (string, optional) — brand-specific subcategory.
- `sentiment` (negative, neutral, positive, mixed).
- `severity` (low, medium, high, critical).
- `action_class` (immediate, sprint, roadmap, fyi, ignore).
- `root_cause_hypothesis` (string) — the agent's diagnosis.
- `summary` (string) — one-line gist.
- `confidence` (float, 0–1).

The `ignore` action class is a first-class output. Most VoC tools fail because they cannot say "this is noise."

### 5.3 Layer 3 — Routing

**Responsibility:** Given a `Classification`, decide which internal owner sees it.

**Interface:** `Router` ABC with method `route(signal, classification) -> Route`.

**v1 implementation:** `RulesRouter` — reads a YAML rules file. Each rule has a `when` clause (predicate over classification fields) and a `route_to` (owner identifier). Top-down evaluation, first match wins, fallthrough to default.

**Example rules file:**
```yaml
default_route: "#triage"
rules:
  - when: { area: "billing", severity: ">=high" }
    route_to: "#finance-urgent"
  - when: { area: "product", action_class: "roadmap" }
    route_to: "@product-pm"
  - when: { source: "twitter", sentiment: "negative", reach: ">10000" }
    route_to: "#pr-watch"
    priority: immediate
```

Owner identifiers (`@product-pm`, `#finance-urgent`) resolve through `brands/<brand>/people.yaml` to actual destinations. This indirection means org changes don't require touching routing rules.

**Escape hatch:** If a brand needs logic too complex for the DSL, they implement a custom `Router` subclass. Documented but rare.

### 5.4 Layer 4 — Memory

**Responsibility:** Append-only persistence of every signal, classification, route, feedback, and outcome.

**Interface:** `Memory` ABC with methods `record_signal`, `record_classification`, `record_route`, `record_feedback`, `record_outcome`, `query`.

**v1 implementation:** `SqlMemory` — SQLAlchemy over SQLite (dev) or Postgres (prod). Schema includes:

- `signals` — raw ingested signals. Append-only.
- `classifications` — one per signal. Foreign key to signal.
- `routes` — one per signal. Foreign key to signal and classification.
- `feedback_events` — many per route (right person? wrong person? acted on? not acted on?).
- `outcomes` — captured when an action ships and the originating signal pattern stops appearing. Many-to-one with the resolved issue.

The schema is the asset. Protect it. Schema changes go through versioned migrations.

### 5.5 Layer 5 — Feedback / Learning loop

**Responsibility:** Capture whether a route was right, whether the action got taken, whether the underlying issue stopped recurring.

**Interface:** `FeedbackChannel` ABC with methods `notify(route)` and `collect_feedback() -> list[FeedbackEvent]`.

**v1 implementation:** `FileFeedback` — writes routed signals to a JSONL file under `data/routes/<brand>/`. Feedback is provided by editing the file (human marks `correct: true/false`). Future implementations: Slack reactions, dashboard buttons, email digest replies.

**Learning, v1:** Feedback is captured but not yet acted upon by the routing engine. Sufficient signal volume is needed before learned weights make sense. v2 introduces a per-brand routing weight model that adjusts confidence on rule matches based on historical feedback.

### 5.6 Cross-cutting: Prompt service

LLM calls happen in the Classifier, but also in onboarding (auto-generating brand context from docs), routing tiebreakers (when rules don't match cleanly), and memory queries (natural-language search). All prompts live in `src/resound/prompts/` as versioned templates. Each prompt has a name, a base template, and accepts a brand context block as a parameter. This keeps prompts out of business logic and makes them iterable independently.

## 6. Brand configuration bundle

Onboarding a new brand produces six files under `brands/<brand>/`:

```
brands/<brand>/
├── brand.yaml          # name, description, primary contacts
├── sources.yaml        # which adapters, with parameters
├── understanding.md    # taxonomy, glossary, examples for Claude
├── routing.yaml        # rules engine config
├── people.yaml         # owner ID → destination resolution
└── views.yaml          # saved dashboards, alert thresholds
```

A solutions engineer (or a technical customer) produces this bundle in an afternoon. v2 introduces a CLI scaffolder (`resound init <brand>`) and an LLM-assisted onboarding flow that drafts `understanding.md` from the brand's public help docs.

## 7. v1 build sequence

**Weekend 1 — Plumbing.**
- Project scaffold, dependencies, .env, repo.
- All five interfaces defined as Python ABCs with stub implementations.
- SQLite schema and migrations.
- Empty signal flowing end-to-end through stubs.
- CLI: `resound run --brand <name>`.

**Weekend 2 — Real intelligence.**
- Reddit source adapter (PRAW).
- Claude classifier with v1 prompt template.
- Rules-based router reading YAML.
- File-based feedback channel.
- Streamlit dashboard with three views (live feed, memory browser, routing audit).

**Weekend 3 — Productize.**
- G2 and Twitter source adapters.
- `liquiddeath` brand config bundle as the canonical example.
- `fulfil` brand config bundle (the pitch artifact).
- README with end-to-end run instructions.
- Public GitHub repo flip.

After weekend 3: the system runs on real public data for at least two configured brands, and adding a third brand is a config-file task.

## 8. Demo plan

Two demos packaged together:

**Demo A — Liquid Death (open-data demo).** Resound running live against Reddit/G2/Twitter for Liquid Death. Shows ingestion volume, classification quality, routing decisions, and the memory layer accumulating. Generic, low-stakes, makes the architecture concrete.

**Demo B — Fulfil internal use case.** Resound configured for Fulfil itself, ingesting public chatter about Fulfil and routing to the internal team. Demonstrates the same engine pointed inward. This is the artifact that goes with the cold pitch.

Future demo C: Resound packaged as a Fulfil-customer extension. Ridge or HexClad configured as a brand, Fulfil offers it as a module. Validates the productization angle without committing to it in v1.

## 9. Success metrics

**v1 engineering metrics:**
- Time from raw signal to routed notification: under 60 seconds.
- Classification accuracy on a hand-labeled set of 100 signals: 80%+ on `is_about_brand` and `area`, 70%+ on `severity`.
- Onboarding time for a new brand (config files only): under 4 hours for a technical user.

**v1 product metrics (once running on a real brand):**
- Routing accuracy as judged by feedback events: 70%+ "right person" rate.
- Volume processed without human intervention: 95%+ (humans only review ambiguous cases).
- Memory layer queryable for "show me all complaints about X in the last quarter" with results returning in under 5 seconds.

## 10. Risks

**Premature abstraction.** Modular interfaces designed before real usage will over-fit imagined needs. Mitigation: build the dumbest possible implementation behind each interface first, refactor only when actual variation forces it.

**Classification cost.** Per-signal Claude calls are not free. At 10,000 signals/month per brand and Claude pricing, monthly cost is meaningful. Mitigation: cache by content hash, batch classify when possible, use Haiku for the `is_about_brand` filter and only escalate to Sonnet/Opus for full classification on relevant signals.

**Source fragility.** Reddit, Twitter, G2 all change APIs and rate limits. Adapters break. Mitigation: each adapter is independently testable, monitored for null returns, and the dashboard surfaces source health.

**Trust in routing.** If the system routes wrongly more than 30% of the time, recipients stop trusting it within two weeks and the loop dies. Mitigation: conservative `ignore` threshold, escalation to a human review queue when confidence is low, prominent feedback affordances.

**Memory privacy.** Customer voice may include PII. Mitigation: strip identifiable info at ingestion when not needed, encrypt the memory store at rest, document data handling for each brand.

## 11. Open questions

- How does Resound handle the same complaint surfacing across multiple sources (e.g., a Reddit post that becomes a Twitter thread that gets quoted in a G2 review)? v1 dedupes by source-specific external_id only; cross-source dedup needs design.
- What's the right cadence for memory-layer summaries to operators? Daily digest? Weekly? On-demand?
- Should the system surface "things that stopped happening" as a first-class signal type? (E.g., complaints about checkout flow vanished after the redesign — that's valuable insight.)
- What's the correct multi-tenant model when a brand grows large and wants per-team Resound deployments?

## 12. Out of scope for this PRD

- Pricing model and packaging for Resound as a commercial product.
- Specific GTM plan for the Fulfil-customer extension angle.
- Long-term competitive positioning vs. Anecdote / Enterpret / Medallia.

These questions will be answered after v1 ships and we have real data on what the system is actually good at.
