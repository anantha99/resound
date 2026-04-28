# Resound

A customer-signal intelligence layer. Resound ingests every public touchpoint about a brand — reviews, social posts, forum discussions — classifies and diagnoses each signal, and routes it to the single internal owner who can act on it. Every signal, route, and outcome accumulates in an append-only memory layer that becomes the brand's living database of customer voice.

> **Status:** v1. Reddit + G2 + Twitter ingestion, Claude classification, rules-based routing, file feedback, Streamlit dashboard. Two brand bundles ship: `liquiddeath` (DTC consumer demo) and `fulfil` (B2B SaaS — the pitch artifact).

See [`docs/PRD.md`](docs/PRD.md) for the full product spec.

## Architecture in one sentence

Five modular layers — Source → Classifier → Router → Memory → Feedback — each defined by an ABC, each pluggable per brand via six configuration files in `brands/<slug>/`.

```
brands/<slug>/
  brand.yaml           # name, description, contacts
  sources.yaml         # which adapters and parameters
  understanding.md     # taxonomy, glossary, examples for the classifier
  routing.yaml         # routing rules
  people.yaml          # owner ID → destination resolution
  views.yaml           # saved dashboard views and alert thresholds
```

Adding a new brand = writing the bundle. No code changes.

## Setup

### 1. Clone and install

```bash
git clone <your-private-repo-url> resound
cd resound
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Fill in:

- `ANTHROPIC_API_KEY` — required.
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` — for the Reddit adapter. Get from https://www.reddit.com/prefs/apps (script-type app, takes 2 minutes).
- `TWITTER_BEARER_TOKEN` — only if you enable the Twitter source (stub in v1).

### 3. Verify the brand bundle

```bash
resound healthcheck --brand liquiddeath
```

You should see source counts, rule counts, and a green check on the API key.

### 4. Run the pipeline

Two brand bundles ship by default:

- `liquiddeath` — DTC consumer brand demo. Reddit-heavy, G2 disabled (not relevant for a beverage brand).
- `fulfil` — B2B SaaS demo (the pitch artifact). Reddit + G2 active, Twitter ready when you add a bearer token.

```bash
# Single ingest cycle:
resound poll-once --brand fulfil

# Or run on a loop:
resound run --brand fulfil --interval-seconds 300
```

The first run will hit the Reddit API, classify each new post via Claude, route per the rules, and write everything to:

- `data/resound.db` — SQLite memory layer
- `data/routes/liquiddeath/<date>.jsonl` — file feedback log

### 5. Open the dashboard

```bash
resound dashboard --brand liquiddeath
```

Streamlit launches at http://localhost:8501 with three views:

1. **Live feed** — most recent ingested signals.
2. **Memory browser** — all persisted signals, filterable, exportable as CSV.
3. **Routing audit** — which rule fired, where each signal went, volume by owner.

## Adding a new brand

1. Copy an existing bundle: `cp -r brands/liquiddeath brands/yourbrand`.
2. Edit the six files. `understanding.md` matters most — give the classifier good examples.
3. Configure routing in `routing.yaml`. Match against any classification field (`area`, `severity`, `sentiment`, `action_class`, `confidence`) plus `source`.
4. Map owner IDs to destinations in `people.yaml`.
5. Run `resound healthcheck --brand yourbrand`, then `resound poll-once --brand yourbrand`.

## Adding a new source

1. Create `src/resound/sources/<source>.py` subclassing `SourceAdapter`.
2. Implement `poll() -> Iterable[RawSignal]`.
3. Register it in `src/resound/sources/__init__.py` `REGISTRY`.
4. Document its expected `params` in the docstring.

That's it. The pipeline, classifier, router, memory, and dashboard pick it up automatically.

## Project layout

```
resound/
├── docs/PRD.md
├── pyproject.toml
├── .env.example
├── brands/
│   └── liquiddeath/        # canonical example bundle
├── src/resound/
│   ├── core/               # the five ABCs
│   ├── sources/            # ingestion adapters (reddit + stubs)
│   ├── classifiers/        # Claude classifier
│   ├── routers/            # rules-based router with predicate DSL
│   ├── memory/             # SQLAlchemy-backed Memory
│   ├── feedback/           # file-based feedback channel
│   ├── prompts/            # versioned LLM prompts
│   ├── dashboard/app.py    # Streamlit UI
│   ├── pipeline.py         # wires the five layers
│   ├── models.py           # Pydantic contracts
│   ├── config.py           # brand config loader
│   └── cli.py              # Typer CLI
└── tests/
```

## Roadmap

- **v1** ✅: Reddit + G2 + Twitter sources, Claude classifier, rules router, file feedback, dashboard. Two brand bundles (`liquiddeath`, `fulfil`).
- **v1.1**: Slack feedback channel; cross-source deduplication (catch the same complaint surfacing across Reddit + Twitter + G2).
- **v2**: Learned routing (use feedback events to adjust rule confidence over time); LLM-assisted brand onboarding (auto-draft `understanding.md` from the brand's help docs); outcome tracking (did the complaint pattern stop after the action shipped?).
- **v3**: Multi-tenant deployment; customer-facing portal where merchants see their own routed signals (the Fulfil-customer extension angle).

## License

Proprietary.
