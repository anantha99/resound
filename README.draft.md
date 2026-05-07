# Resound

A customer-signal intelligence layer for D2C brands. Resound ingests every public touchpoint about a brand — Reddit threads, reviews, social posts — classifies and diagnoses each signal, and routes it to the single internal owner who can act on it. Every signal, route, and outcome accumulates in an append-only memory layer that becomes the brand's living database of customer voice.

> **Status:** Hiring-pitch artifact for Fulfil. This is a working, deployable demo — not a v1 product release. Reddit ingestion, OpenRouter classification, rules-based routing, append-only memory with a queryable LLM audit trail, and a Streamlit dashboard all run end-to-end. Two brand bundles ship — `liquiddeath` and `ridge`, both Fulfil customers — demonstrating that adding a brand is a configuration task, not an engineering one.

## The pitch

Every D2C brand on Fulfil's platform — Liquid Death, Ridge, HexClad, Hims & Hers — has the same blind spot: customer voice is scattered across Reddit, G2, Twitter, with no shared memory and no closed loop. Brands lose deals over objections that product would have heard six months ago. Existing voice-of-customer tools (Anecdote, Enterpret, Medallia) help with aggregation but stop at dashboards — they don't route to owners, they don't track outcomes, and the resulting database belongs to the vendor, not the brand.

Resound is a Fulfil-platform extension your customers could opt into. Brands keep the data, the routing decisions, and the outcomes. Five years in, a Resound deployment is a memory layer no competitor can replicate overnight. Onboarding a new brand is a YAML exercise — no engineering work — which is what makes this a productizable line across Fulfil's book, not a one-off integration.

## Architecture in one diagram

Five modular layers plus one cross-cutting LLM gateway. Each layer defines an interface; concrete implementations are pluggable per brand.

```
                          ┌──────────────────────┐
                          │     LLM Gateway      │   • OpenRouter (200+ models)
                          │   one path, any      │   • retry + fallback chain
                          │       model          │   • per-stage models.yaml
                          └──────────▲───────────┘   • llm_calls audit trail
                                     │
   Source ──▶ Classifier ──▶ Router ──▶ Memory ──▶ Feedback
   Reddit      OpenRouter     Rules     SQLite      File
              (Claude/GPT/    engine    (append-    (Slack/email
               Gemini/etc.)             only)        v2)
```

Per-brand configuration lives entirely in `brands/<slug>/`:

```
brands/liquiddeath/
  brand.yaml         # name, description, contacts
  sources.yaml       # which adapters + parameters (subreddits, search terms)
  understanding.md   # taxonomy, glossary, examples — the classifier's brand context
  routing.yaml       # routing rules (severity → owner, area → channel, etc.)
  people.yaml        # owner ID → Slack/email resolution
  views.yaml         # saved dashboard views + alert thresholds
  models.yaml        # per-stage model overrides (optional)
```

Adding a new brand = creating the bundle. **Zero code changes.**

## Quickstart

### 1. Clone and install

```bash
git clone <your-private-repo-url> resound
cd resound
python -m venv .venv && source .venv/bin/activate    # .venv\Scripts\activate on Windows
pip install -e .
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Fill in:

- `OPENROUTER_API_KEY` — one key, ~300 models. Get from <https://openrouter.ai/keys>.
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` — script-type app at <https://www.reddit.com/prefs/apps>, takes ~2 minutes.

Model selection lives in `config/models.yaml` (with optional per-brand overrides at `brands/<slug>/models.yaml`). The default classify model is `anthropic/claude-sonnet-4-6` with fallbacks to `openai/gpt-4.1` and `google/gemini-2.5-pro`. To switch a brand to a different model, edit one line of YAML and restart — no code.

### 3. Verify the bundle

```bash
resound healthcheck --brand liquiddeath
```

Expected output:

```
Liquid Death (liquiddeath)
  description: Canned water with edgy heavy-metal branding...
  sources configured: ['reddit']
  routing rules: 8
  people entries: 3
  channel entries: 6
  understanding doc: 1834 chars
  classify model: anthropic/claude-sonnet-4-6
    source: brand override (brands/liquiddeath/models.yaml)
    fallbacks: openai/gpt-4.1, google/gemini-2.5-pro
    timeout: 30s
  ✓ OPENROUTER_API_KEY set
```

The `source:` line is the diagnostic that catches "I edited models.yaml but nothing changed" — it shows whether the brand override is taking effect or you're falling through to the global default.

### 4. Run the pipeline

```bash
# Single ingest cycle:
resound poll-once --brand liquiddeath

# Or run on a loop:
resound run --brand liquiddeath --interval-seconds 300
```

The pipeline pulls fresh signals from Reddit, classifies each via OpenRouter, routes per the rules, and writes everything to:

- `data/resound.db` — SQLite memory layer with five tables: `signals`, `classifications`, `routes`, `feedback_events`, and `llm_calls` (the LLM audit trail — model used, tokens, cost, latency, was_fallback, attempt_count for every gateway call)
- `data/routes/<brand>/<date>.jsonl` — file feedback log

### 5. Open the dashboard

```bash
resound dashboard --brand liquiddeath
```

Streamlit launches at <http://localhost:8501> with three views:

1. **Live feed** — most recent ingested signals with their classifications
2. **Memory browser** — all persisted signals, filterable, exportable as CSV
3. **Routing audit** — which rule fired, where each signal went, volume by owner

## Adding a new brand

The whole loop is 30–45 minutes if you take `understanding.md` seriously, less if you don't.

1. **Copy an existing bundle**: `cp -r brands/liquiddeath brands/yourbrand`
2. **Edit four files** — the others can stay as-is:
   - `brand.yaml` — name + 1-line description (the description becomes part of the classifier's brand context)
   - `sources.yaml` — change `subreddits:` and `search_terms:` to the new brand's
   - `understanding.md` — taxonomy, glossary, and 4 worked examples. **This is the leverage point for classification quality.** Bad `understanding.md` = bad classifications. Spend the time here.
   - `routing.yaml` — adjust rule names if the brand category is different (drop `ops_retail_availability` for non-retail brands, etc.)
3. **Optional**: `models.yaml` if you want a different classify model for this brand
4. **Verify**: `resound healthcheck --brand yourbrand`
5. **Run**: `resound poll-once --brand yourbrand`

## Project layout

```
resound/
├── docs/
│   ├── PRD-openrouter.txt         # full product PRD (v1.1, OpenRouter edition)
│   ├── PRD-demo.md                # demo execution PRD
│   ├── ARCHITECTURE.md            # architecture diagram + layer contracts
│   └── design_decisions.md        # locked design decisions per task (#1–#44)
├── pyproject.toml
├── .env.example
├── config/
│   └── models.yaml                # global default per-stage model selection
├── brands/
│   ├── liquiddeath/               # canonical brand bundle (DTC consumer)
│   ├── ridge/                     # second brand bundle (DTC accessories)
│   └── fulfil/                    # bonus: "you could even point this at yourselves"
├── src/resound/
│   ├── core/                      # the five layer ABCs
│   ├── sources/                   # ingestion: reddit + g2/twitter stubs
│   ├── classifiers/               # OpenRouter-backed classifier (uses gateway)
│   ├── routers/                   # rules engine with predicate DSL
│   ├── memory/                    # SQLAlchemy-backed memory + llm_calls audit writers
│   ├── feedback/                  # file-based feedback channel
│   ├── prompts/                   # versioned LLM prompt templates
│   ├── gateway/                   # the LLM gateway (OpenRouter, retry, fallback, models.yaml)
│   ├── dashboard/app.py           # Streamlit UI
│   ├── pipeline.py                # wires the five layers
│   ├── models.py                  # Pydantic contracts
│   ├── config.py                  # brand config loader
│   └── cli.py                     # Typer CLI
└── tests/                         # unit + smoke tests; offline (no live API calls)
```

## Source coverage

| Source | Status | Notes |
|---|---|---|
| Reddit | ✅ Fully wired | Uses PRAW; configured per brand via subreddits + search terms |
| G2 | 🟡 Scaffolded, off by default | HTML scrape; Cloudflare-blocks unpredictably; behind `enabled: false` flag |
| Twitter | 🟡 Scaffolded, off by default | API v2 with bearer token; useful volume requires paid tier |

Honesty as defense: a reviewer asking "why isn't G2 working?" gets the same answer the README does — rate-limit fragility is in scope to acknowledge, not in scope to fix in this artifact.

## What's in scope and what's deferred

This is a working demo, deliberately tight in scope. Everything below is honest about what is and isn't built.

**In scope (works end-to-end):**

- Reddit ingestion → OpenRouter classification → rules-based routing → SQLite memory → Streamlit dashboard
- Single LLM gateway with retry, fallback chains, per-stage model selection via `config/models.yaml`, overridable per brand at `brands/<slug>/models.yaml`
- `llm_calls` audit table populated on every classification call (`stage`, `model`, `prompt_hash`, `response_content`, `tokens_in`, `tokens_out`, `cost_usd`, `latency_ms`, `was_fallback`, `attempt_count`, `success`, `error_class`, `error_message`)
- Two complete brand bundles (`liquiddeath`, `ridge`) demonstrating the config-only onboarding story
- CLI: `poll-once`, `run`, `healthcheck`, `dashboard`
- Layered exception handling: gateway config/auth errors are fatal (loud failure on misconfiguration); recoverable errors produce stub classifications that flow through the pipeline so failures become data rather than disappear

**Deliberately deferred (see [`docs/PRD-demo.md`](docs/PRD-demo.md) §5.2):**

- Two-stage filter→classify pipeline — single classify is enough for current scope; cost optimization deferred
- LLM-based routing tiebreaker — rules + default route handle this
- Natural-language memory search — memory browser uses structured filters
- LLM telemetry dashboard tab — audit data is queryable; UI deferred to next iteration
- Docker / docker-compose — single-command Python install works; containerization deferred
- Operator runbook
- Slack/email feedback delivery — file-based today; integration deferred

**Not in this version (v2 territory):**

- Multi-language signals (English only)
- Private channels (support tickets, Gong, Zendesk) — requires per-customer integrations
- Action automation — humans take action; system tracks the outcome
- Customer-facing portal — merchants viewing their own routed signals

## Testing

```bash
pytest
```

Tests are offline by design — no live API calls, no `OPENROUTER_API_KEY` required. The classifier is exercised against a `FakeGateway`; a smoke test wires a real `OpenRouterClassifier` through a real `Pipeline` against a real `SqlMemory` (with `FakeGateway` standing in for the network) to assert the audit trail populates end-to-end.

## License

Proprietary. See [`LICENSE`](LICENSE).

## References

- [`docs/PRD-openrouter.txt`](docs/PRD-openrouter.txt) — full product PRD (v1.1 OpenRouter edition)
- [`docs/PRD-demo.md`](docs/PRD-demo.md) — demo execution PRD (artifact-level spec)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — architecture diagram + layer contracts
- [`docs/design_decisions.md`](docs/design_decisions.md) — locked design decisions per task (#1–#44)
