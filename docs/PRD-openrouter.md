# Resound — Product Requirements Document (OpenRouter Edition)

**Version:** 1.1 (v1 scope, OpenRouter-based LLM layer)
**Status:** Draft
**Last updated:** April 2026
**Format:** Taskmaster-AI compatible (one feature per numbered subsection; each subsection is independently decomposable into a task with acceptance criteria)

---

## 1. Summary

Resound is a customer-signal intelligence layer that ingests every public touchpoint about a brand — reviews, social posts, forum discussions, support tickets — classifies and diagnoses each signal, and routes it to the single internal owner who can act on it. Every signal, route, and outcome is captured in an append-only memory layer that becomes the brand's living database of customer voice.

**Change vs v1.0:** The LLM layer is no longer hard-bound to the Anthropic Claude SDK. All model calls are made through **OpenRouter**, a unified gateway that exposes 200+ models (Claude, GPT, Gemini, Llama, Mistral, Qwen, DeepSeek, etc.) behind a single OpenAI-compatible API. Operators choose models per pipeline stage in `models.yaml`. This makes the system provider-agnostic, lets operators trade off cost vs. quality per stage, and provides automatic fallbacks if a provider degrades.

The thesis is unchanged: voice-of-customer tools today are services brands rent. Resound keeps the data, routing decisions, and outcomes inside the company. Five years in, a Resound deployment is a memory layer no competitor can replicate overnight.

The system is modular and brand-configurable. Seven YAML/markdown files (six brand-config files plus the new `models.yaml`) describe a brand's sources, taxonomy, routing rules, org structure, and model selection. Onboarding a new brand is a configuration task, not an engineering one.

## 2. Problem

Customer voice is scattered. A complaint about bundle accounting might land in a G2 review, a Trustpilot star, a Reddit thread, a support ticket, and an NPS free-text — five places, five owners, no shared memory, no closed loop.

The cost is invisible but huge. The same issue gets relitigated every quarter because nobody remembers it was solved last year. Engineering builds features that customer success already heard weren't wanted. Sales loses deals over objections that product would have addressed in a sprint had they known. Knowledge that should be a strategic asset stays trapped as tribal lore in individual heads.

Existing voice-of-customer tools (Anecdote, Enterpret, Medallia) help with aggregation but stop at dashboards. They don't route to the right person, they don't track whether the action got taken, they don't close the loop, and the resulting database belongs to the vendor — not the brand.

A secondary problem this revision addresses: **vendor lock-in at the LLM layer.** Brands deploying Resound on-prem or in regulated industries cannot always use a single provider — some require open-weight models, some require US-only inference, some have negotiated rates with a specific vendor. The system must accommodate model choice without code changes.

## 3. Goals

### 3.1 v1 functional goals (3 weekends, end of week 3)

- Ingest signals from at least three public sources (Reddit, G2, Twitter/X) for one configured brand.
- Classify each signal by functional area, severity, and required action class using **any model available through OpenRouter**, selectable per stage in config.
- Route each signal to the correct internal owner via a configurable rules engine.
- Persist every signal, classification, route, and feedback event in an append-only memory layer.
- Provide a dashboard showing the live signal feed, the memory browser, the routing audit log, and per-model cost/latency telemetry.
- Demonstrate end-to-end onboarding of a new brand by editing seven configuration files only — no code changes.
- Demonstrate hot-swapping the classification model from `anthropic/claude-sonnet-4-6` to `openai/gpt-4.1-mini` to `meta-llama/llama-3.1-70b-instruct` by editing `models.yaml` and restarting — no code changes.

### 3.2 v1 deployability goals

- Single-command local run: `resound run --brand <name>`.
- Single-command containerized run: `docker compose up`.
- Production-ready deployment artifact: Dockerfile + docker-compose.yml + `.env.example` + Postgres-backed memory.
- One-page operator runbook for adding a new brand and rotating API keys.

### 3.3 Non-goals for v1 (explicit deferrals)

- Learned/ML-based routing — v1 uses LLM + rules, learning loop is captured but not yet acted on.
- Private channel ingestion (support tickets, Gong calls, Zendesk) — these need per-customer integrations and are v2.
- Multi-language signals — English only.
- Action automation — humans take action, system tracks the outcome.
- SLA management or escalation chains — v2.
- Customer-facing portal where merchants see their own routed signals — v3.
- Self-hosted model serving (Ollama, vLLM) — v2. v1 uses OpenRouter exclusively for LLM access.

## 4. Users

**Primary user (operator):** Internal product/engineering/CX leader at the deployed brand. They configure routing rules, monitor the signal feed, intervene when routing is wrong, and use the memory layer for retrospectives and roadmap planning. They also pick models in `models.yaml` based on cost/quality tradeoffs.

**Secondary user (recipient):** The individual employee Resound routes a signal to. Receives a notification (file-based in v1, Slack/email later), acts on the signal, and provides feedback (right person? wrong person?) so the system learns.

**Tertiary user (strategic):** Founder/CEO using the memory layer as a quarterly input — what's our customer actually saying, what changed, what stopped showing up.

## 5. Architecture

Five modular layers plus one cross-cutting LLM gateway. Each layer defines an interface; concrete implementations are pluggable per brand. Configuration determines which implementations are active.

### 5.1 Layer 1 — Ingestion

**Responsibility:** Pull raw signals from external surfaces. Normalize to a common schema. Dedupe.

**Interface:** `SourceAdapter` ABC with methods `poll() -> list[RawSignal]`, `name`, `dedupe_key(signal)`.

**v1 implementations:**
- `RedditSource` — uses PRAW, polls configured subreddits and brand-name search.
- `G2Source` — HTML-scrape based; polls brand review pages on a schedule.
- `TwitterSource` — uses Twitter API v2 with bearer token; polls brand mentions and hashtags.

**Common schema (`RawSignal`):** source, external_id, url, author_handle, content, posted_at, raw_metadata.

**Configuration:** `brands/<brand>/sources.yaml` lists active adapters and parameters. Credentials live in `.env`, never in the brand config.

**Acceptance criteria:**
- Each adapter returns a list of `RawSignal` instances when polled.
- Each adapter is independently testable with a mock HTTP layer.
- Dedupe by `(source, external_id)` prevents the same signal from being persisted twice.
- Adapter failures (rate limit, network error) are logged but do not crash the pipeline.

### 5.2 Layer 2 — Understanding

**Responsibility:** For each raw signal, decide if it's relevant, what it's about, how serious it is, what action class it warrants.

**Interface:** `Classifier` ABC with method `classify(raw: RawSignal, brand_context: str) -> Classification`.

**v1 implementation:** `OpenRouterClassifier` — issues a chat-completion call through the OpenRouter gateway (see §5.6) with structured JSON output. Brand-specific context (taxonomy, glossary, examples) is injected from `brands/<brand>/understanding.md`.

**Two-stage classification (cost optimization):**
1. **Filter stage** — a cheap, fast model (default `openai/gpt-4.1-mini` or `anthropic/claude-haiku-4-5`) decides `is_about_brand` only. ~70% of raw signals are filtered out here.
2. **Full classification stage** — a higher-quality model (default `anthropic/claude-sonnet-4-6` or `openai/gpt-4.1`) runs only on signals that passed the filter, returning the full `Classification` schema.

Both stages are configured in `models.yaml`; either can be set to any OpenRouter-available model.

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
- `model_used` (string) — the OpenRouter model slug that produced this classification (audit trail).
- `tokens_in`, `tokens_out`, `cost_usd` (audit trail; surfaced in dashboard).

The `ignore` action class is a first-class output. Most VoC tools fail because they cannot say "this is noise."

**Acceptance criteria:**
- Filter stage rejects irrelevant signals with cost ≤ $0.001/signal.
- Full classification produces valid JSON conforming to the schema 99%+ of the time; invalid JSON triggers a retry with a stricter prompt.
- Switching the filter model or classification model in `models.yaml` requires no code change.
- Each classification stores `model_used`, `tokens_in`, `tokens_out`, `cost_usd` for auditability.

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

**LLM tiebreaker:** When no rule matches and the classification is ambiguous (`confidence < 0.6`), the router can optionally call a small model through the gateway to pick between top candidate owners. Configurable in `models.yaml` as the `routing_tiebreaker` stage.

**Escape hatch:** If a brand needs logic too complex for the DSL, they implement a custom `Router` subclass. Documented but rare.

**Acceptance criteria:**
- Rule evaluation is deterministic and order-preserving.
- Owner resolution returns a concrete destination string or raises a clear error.
- The full rule trace (which rules matched, which fell through) is recorded on the `Route` for audit.

### 5.4 Layer 4 — Memory

**Responsibility:** Append-only persistence of every signal, classification, route, feedback, and outcome.

**Interface:** `Memory` ABC with methods `record_signal`, `record_classification`, `record_route`, `record_feedback`, `record_outcome`, `query`.

**v1 implementation:** `SqlMemory` — SQLAlchemy over SQLite (dev) or Postgres (prod). Schema includes:
- `signals` — raw ingested signals. Append-only.
- `classifications` — one per signal. Foreign key to signal. Includes `model_used`, `tokens_in`, `tokens_out`, `cost_usd`.
- `routes` — one per signal. Foreign key to signal and classification.
- `feedback_events` — many per route (right person? wrong person? acted on? not acted on?).
- `outcomes` — captured when an action ships and the originating signal pattern stops appearing. Many-to-one with the resolved issue.
- `llm_calls` — every LLM invocation (filter, classify, tiebreaker, onboarding, query). Captures stage, model, prompt hash, response hash, tokens, cost, latency, success/failure.

Schema changes go through versioned Alembic migrations.

**Acceptance criteria:**
- All five record methods are idempotent given the same input.
- Foreign keys are enforced.
- The `llm_calls` table allows reconstructing per-brand monthly LLM spend by stage and model.
- Migrations are reversible.

### 5.5 Layer 5 — Feedback / Learning loop

**Responsibility:** Capture whether a route was right, whether the action got taken, whether the underlying issue stopped recurring.

**Interface:** `FeedbackChannel` ABC with methods `notify(route)` and `collect_feedback() -> list[FeedbackEvent]`.

**v1 implementation:** `FileFeedback` — writes routed signals to a JSONL file under `data/routes/<brand>/`. Feedback is provided by editing the file (human marks `correct: true/false`). Future implementations: Slack reactions, dashboard buttons, email digest replies.

**Learning, v1:** Feedback is captured but not yet acted upon by the routing engine. Sufficient signal volume is needed before learned weights make sense. v2 introduces a per-brand routing weight model that adjusts confidence on rule matches based on historical feedback.

**Acceptance criteria:**
- Routed signals appear in the JSONL file within 1 second of routing.
- Feedback file is parsed on each pipeline run; new events are persisted to `feedback_events`.
- Malformed feedback entries are logged and skipped, not fatal.

### 5.6 Cross-cutting: LLM gateway (OpenRouter)

This is the central architectural change in v1.1.

**Responsibility:** Be the single chokepoint for every LLM call in the system. Handle authentication, model selection, retries, fallbacks, structured output enforcement, cost tracking, and prompt versioning.

**Interface:** `LLMGateway` class with method:
```python
def complete(
    self,
    stage: str,                 # "filter" | "classify" | "routing_tiebreaker" | "onboarding" | "memory_query"
    prompt: str,
    response_schema: dict | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1024,
) -> LLMResponse
```

`LLMResponse` carries: `content`, `model_used`, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `raw_response`.

**Implementation:** `OpenRouterGateway` — uses `openai` Python SDK with `base_url="https://openrouter.ai/api/v1"` and `api_key=$OPENROUTER_API_KEY`. The SDK is OpenAI-compatible, so the same client works for every provider OpenRouter exposes.

**Required HTTP headers (per OpenRouter docs):**
- `HTTP-Referer: https://github.com/<org>/resound` — optional, helps with leaderboards.
- `X-Title: Resound` — optional, app identifier.

**Model selection:** The gateway looks up `models.yaml` to map a stage name to a model slug:

```yaml
# brands/<brand>/models.yaml  (or a global default at config/models.yaml)
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
  onboarding:
    model: anthropic/claude-sonnet-4-6
    temperature: 0.3
    max_tokens: 4096
  memory_query:
    model: openai/gpt-4.1-mini
    temperature: 0.2
    max_tokens: 512

# Optional per-brand overrides
brand_overrides:
  liquiddeath:
    classify:
      model: openai/gpt-4.1
```

**Structured output:** The gateway requests JSON-mode output (`response_format: {"type": "json_object"}`) when `response_schema` is provided. For models that don't support JSON mode, the gateway falls back to a "JSON only, no prose" prompt suffix and a JSON-extraction regex.

**Retry & fallback policy:**
- Transient errors (5xx, timeout, rate limit): exponential backoff, max 3 retries.
- Permanent errors (4xx other than 429): immediately fall through to the next model in the `fallbacks` list.
- If all fallbacks fail: raise `LLMGatewayError`; the pipeline records the failure and skips the signal (it remains in `signals` with no classification, surfaced on the dashboard for manual review).

**Cost tracking:** Every call writes a row to the `llm_calls` table with stage, model, tokens, cost (parsed from OpenRouter's `usage.cost` field when available, computed from `usage.tokens` × OpenRouter price-list otherwise), and latency.

**Prompt service:** All prompts live in `src/resound/prompts/` as versioned templates. Each prompt has a name (matching a stage), a base template, and accepts a brand context block as a parameter. Prompts are loaded by the gateway on instantiation; changes require a process restart.

**Secrets:** `OPENROUTER_API_KEY` is the single required LLM-related env var. Optional: `OPENROUTER_PROVIDER_PREFERENCES` for prefer/avoid lists (e.g., avoid certain providers for compliance).

**Acceptance criteria:**
- A single env var (`OPENROUTER_API_KEY`) is sufficient to access every supported model.
- Switching `models.yaml` from `anthropic/claude-sonnet-4-6` to `openai/gpt-4.1` and restarting causes the next classification to use the new model, with no code changes.
- A simulated provider outage on the primary model triggers automatic fallback to the next in the list, recorded in `llm_calls`.
- Per-call cost is recorded within ±10% of the OpenRouter dashboard's reported cost.
- The dashboard shows monthly spend grouped by stage and by model.

## 6. Brand configuration bundle

Onboarding a new brand produces seven files under `brands/<brand>/`:

```
brands/<brand>/
├── brand.yaml          # name, description, primary contacts
├── sources.yaml        # which adapters, with parameters
├── understanding.md    # taxonomy, glossary, examples for the LLM
├── routing.yaml        # rules engine config
├── people.yaml         # owner ID → destination resolution
├── views.yaml          # saved dashboards, alert thresholds
└── models.yaml         # per-stage model selection (overrides global defaults)
```

A solutions engineer (or a technical customer) produces this bundle in an afternoon. v2 introduces a CLI scaffolder (`resound init <brand>`) and an LLM-assisted onboarding flow that drafts `understanding.md` from the brand's public help docs.

## 7. v1 build sequence

The build is decomposed into sequential, independently shippable milestones. Each milestone is a Taskmaster-friendly batch.

### 7.1 Milestone M1 — Project scaffolding

- Initialize Python project (`pyproject.toml`, `uv` or `poetry`).
- Set up directory structure: `src/resound/{ingest,understand,route,memory,feedback,gateway,prompts,cli}`, `brands/`, `config/`, `data/`, `tests/`.
- Add `.env.example`, `.gitignore`, `README.md` skeleton.
- CI pipeline (GitHub Actions): lint (`ruff`), type check (`mypy`), test (`pytest`).
- Dockerfile and `docker-compose.yml` (Postgres + app).

### 7.2 Milestone M2 — Core interfaces and SQLite memory

- Define ABCs: `SourceAdapter`, `Classifier`, `Router`, `Memory`, `FeedbackChannel`, `LLMGateway`.
- Implement `SqlMemory` over SQLite with full schema and Alembic migrations.
- Implement stub `SourceAdapter`, `Classifier`, `Router`, `FeedbackChannel`.
- Wire pipeline orchestrator: `Pipeline.run()` polls sources → classifies → routes → records.
- CLI entry: `resound run --brand <name>`.
- Unit tests for memory CRUD and pipeline orchestration.

### 7.3 Milestone M3 — OpenRouter gateway

- Implement `OpenRouterGateway` using the `openai` Python SDK.
- Load `models.yaml` (global + per-brand overrides) at startup.
- Implement retry-with-backoff and fallback chains.
- Implement JSON-mode handling with regex fallback for non-JSON-mode models.
- Implement `llm_calls` recording with stage, model, tokens, cost, latency.
- Mock the OpenRouter API in tests; cover happy path, rate-limit retry, fallback, all-fail.
- Add `resound models test --stage classify` debug command that runs a sample prompt through the configured model and prints the result.

### 7.4 Milestone M4 — Reddit ingestion + classification

- Implement `RedditSource` using PRAW.
- Implement `OpenRouterClassifier` with two-stage filter→classify flow.
- Author the v1 prompt templates: `filter.md`, `classify.md`, `routing_tiebreaker.md`.
- Author `understanding.md` for `liquiddeath`.
- End-to-end smoke test: poll r/liquiddeath, classify 20 signals, persist to memory.

### 7.5 Milestone M5 — Routing + feedback

- Implement `RulesRouter` with the YAML DSL.
- Implement owner resolution via `people.yaml`.
- Implement LLM tiebreaker path through the gateway.
- Implement `FileFeedback` (JSONL writer + reader).
- Author `routing.yaml` and `people.yaml` for `liquiddeath`.
- End-to-end test: classified signals route to the expected owners.

### 7.6 Milestone M6 — Dashboard

- Streamlit (or FastAPI + minimal HTMX) app with four views:
  1. **Live feed** — recent signals + classifications, filterable.
  2. **Memory browser** — query interface (free-text + filters); free-text uses `memory_query` LLM stage.
  3. **Routing audit** — every route with rule trace and feedback status.
  4. **LLM telemetry** — monthly spend by stage and model, latency p50/p95, fallback rate.

### 7.7 Milestone M7 — Additional sources

- Implement `G2Source` (HTML scrape).
- Implement `TwitterSource` (API v2).
- Per-source rate-limit handling and source-health surface in the dashboard.

### 7.8 Milestone M8 — Second brand bundle + productization

- Author `fulfil` brand bundle (the pitch artifact).
- README with end-to-end run instructions for both brands.
- Operator runbook: `docs/RUNBOOK.md` covering install, brand onboarding, model switching, key rotation.
- Production docker-compose with Postgres, env templating, healthchecks.
- Public GitHub repo flip.

After M8: the system runs on real public data for at least two configured brands, deploys with one command, and switches LLM providers via a single config edit.

## 8. Demo plan

Two demos packaged together:

**Demo A — Liquid Death (open-data demo).** Resound running live against Reddit/G2/Twitter for Liquid Death. Shows ingestion volume, classification quality, routing decisions, the memory layer accumulating, and the LLM telemetry view. During the demo we live-switch the classification model from Claude Sonnet to GPT-4.1 to demonstrate provider flexibility.

**Demo B — Fulfil internal use case.** Resound configured for Fulfil itself, ingesting public chatter about Fulfil and routing to the internal team. Demonstrates the same engine pointed inward. This is the artifact that goes with the cold pitch.

Future demo C: Resound packaged as a Fulfil-customer extension. Ridge or HexClad configured as a brand, Fulfil offers it as a module.

## 9. Success metrics

### 9.1 Engineering metrics

- Time from raw signal to routed notification: under 60 seconds.
- Classification accuracy on a hand-labeled set of 100 signals: 80%+ on `is_about_brand` and `area`, 70%+ on `severity`.
- Onboarding time for a new brand (config files only): under 4 hours for a technical user.
- Model swap time (edit `models.yaml`, restart, verify): under 2 minutes.
- LLM gateway p95 latency: under 8 seconds end-to-end (filter + classify combined).

### 9.2 Product metrics (once running on a real brand)

- Routing accuracy as judged by feedback events: 70%+ "right person" rate.
- Volume processed without human intervention: 95%+ (humans only review ambiguous cases).
- Memory layer queryable for "show me all complaints about X in the last quarter" with results returning in under 5 seconds.

### 9.3 Cost metrics

- Filter stage cost per 1000 signals: under $0.50.
- Full classification cost per 1000 *relevant* signals (post-filter): under $5.00 with default model selection.
- Cost dashboard reconciles to OpenRouter's billing dashboard within ±10%.

## 10. Risks

**Premature abstraction.** Modular interfaces designed before real usage will over-fit imagined needs. Mitigation: build the dumbest possible implementation behind each interface first, refactor only when actual variation forces it.

**Classification cost.** Per-signal LLM calls are not free. At 10,000 signals/month per brand, monthly cost is meaningful. Mitigation: two-stage filter→classify, cache by content hash, batch when the chosen model supports it, expose model selection in `models.yaml` so operators can downgrade for cost.

**OpenRouter dependency.** OpenRouter is now a single point of failure for all LLM access. Mitigation: (1) the gateway's fallback chain spans multiple underlying providers, so OpenRouter being up is sufficient even if one provider is down; (2) v2 adds an alternate gateway implementation (direct provider SDKs or self-hosted) behind the same interface.

**Model drift.** A model behind a slug may change behavior over time (provider updates, OpenRouter routing changes). Mitigation: prompt+model+output triples are hashed and stored in `llm_calls`; we can detect distributional drift on classifications month-over-month.

**Source fragility.** Reddit, Twitter, G2 all change APIs and rate limits. Mitigation: each adapter is independently testable, monitored for null returns, dashboard surfaces source health.

**Trust in routing.** If the system routes wrongly more than 30% of the time, recipients stop trusting it within two weeks and the loop dies. Mitigation: conservative `ignore` threshold, escalation to a human review queue when confidence is low, prominent feedback affordances.

**Memory privacy.** Customer voice may include PII. Mitigation: strip identifiable info at ingestion when not needed, encrypt the memory store at rest, document data handling for each brand. OpenRouter request logging can be disabled per-call via headers when handling sensitive content.

## 11. Open questions

- Cross-source dedup: how does Resound handle the same complaint surfacing across multiple sources (Reddit post → Twitter thread → G2 quote)? v1 dedupes by source-specific external_id only.
- Memory-summary cadence: daily digest? Weekly? On-demand?
- Should the system surface "things that stopped happening" as a first-class signal type?
- Multi-tenant model when a brand grows large and wants per-team Resound deployments?
- Should `models.yaml` support per-signal-area model overrides (e.g., legal/billing signals always use a specific compliant model)?

## 12. Out of scope for this PRD

- Pricing model and packaging for Resound as a commercial product.
- Specific GTM plan for the Fulfil-customer extension angle.
- Long-term competitive positioning vs. Anecdote / Enterpret / Medallia.
- Self-hosted model serving (Ollama, vLLM, TGI). v2 candidate.

---

## Appendix A — Technology stack

- **Language:** Python 3.12+
- **Package manager:** `uv` (fastest, lockfile-first) or `poetry`
- **LLM gateway:** `openai>=1.40` SDK pointed at OpenRouter (`base_url="https://openrouter.ai/api/v1"`)
- **DB:** SQLite (dev), Postgres 16 (prod), SQLAlchemy 2.x ORM, Alembic migrations
- **Reddit:** `praw`
- **Twitter:** `tweepy` (API v2)
- **G2:** `httpx` + `selectolax` for HTML parsing
- **Dashboard:** Streamlit (v1; trade up to FastAPI + a static frontend in v2 if needed)
- **Config parsing:** `pydantic` v2 + `pyyaml`
- **Testing:** `pytest`, `pytest-asyncio`, `respx` (HTTP mocking)
- **Lint/type:** `ruff`, `mypy`
- **Container:** Dockerfile (slim Python base) + `docker-compose.yml`
- **CI:** GitHub Actions (lint, type, test, build image)

## Appendix B — Repository layout

```
resound/
├── pyproject.toml
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── README.md
├── docs/
│   ├── PRD-openrouter.md  (this file)
│   └── RUNBOOK.md
├── config/
│   └── models.yaml        # global defaults
├── brands/
│   └── liquiddeath/
│       ├── brand.yaml
│       ├── sources.yaml
│       ├── understanding.md
│       ├── routing.yaml
│       ├── people.yaml
│       ├── views.yaml
│       └── models.yaml    # optional per-brand overrides
├── src/resound/
│   ├── __init__.py
│   ├── cli.py
│   ├── pipeline.py
│   ├── ingest/
│   │   ├── base.py
│   │   ├── reddit.py
│   │   ├── g2.py
│   │   └── twitter.py
│   ├── understand/
│   │   ├── base.py
│   │   └── openrouter_classifier.py
│   ├── route/
│   │   ├── base.py
│   │   └── rules_router.py
│   ├── memory/
│   │   ├── base.py
│   │   ├── sql_memory.py
│   │   └── migrations/
│   ├── feedback/
│   │   ├── base.py
│   │   └── file_feedback.py
│   ├── gateway/
│   │   ├── base.py
│   │   ├── openrouter.py
│   │   └── models_config.py
│   ├── prompts/
│   │   ├── filter.md
│   │   ├── classify.md
│   │   ├── routing_tiebreaker.md
│   │   ├── onboarding.md
│   │   └── memory_query.md
│   └── dashboard/
│       └── app.py
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

## Appendix C — Environment variables

```
# Required
OPENROUTER_API_KEY=...
RESOUND_BRAND=liquiddeath
RESOUND_DB_URL=sqlite:///./data/resound.db   # or postgresql://...

# Source credentials (only required for adapters in active use)
REDDIT_CLIENT_ID=...
REDDIT_CLIENT_SECRET=...
REDDIT_USER_AGENT=resound/0.1
TWITTER_BEARER_TOKEN=...

# Optional
OPENROUTER_HTTP_REFERER=https://github.com/<org>/resound
OPENROUTER_APP_TITLE=Resound
LOG_LEVEL=INFO
```

## Appendix D — Mapping to Taskmaster tasks

This PRD is structured so that each `### 5.x` subsection and each `### 7.x` milestone maps cleanly to a Taskmaster top-level task. Recommended decomposition when running `task-master parse-prd`:

- One task per **architecture layer** (§5.1–§5.6) covering interface + v1 implementation + unit tests.
- One task per **build milestone** (§7.1–§7.8) covering integration and end-to-end verification.
- Cross-cutting tasks: documentation (README, RUNBOOK), CI/CD pipeline, dockerization, and release prep.
- Each task should reference the corresponding **Acceptance criteria** block in §5 as its Definition of Done.
