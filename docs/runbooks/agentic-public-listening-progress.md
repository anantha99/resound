# Agentic Public Listening Progress

Last updated: 2026-07-09

This is the current handoff for the Apify-backed, LangGraph-agentic public-listening backend.

## Current Status

- The backend can ingest public Reddit data through Apify for a manually seeded brand profile.
- The durable/public-listening path now uses LangGraph-backed signal triage by default.
- Signal triage has two agent stages:
  - `classify`: classify the raw signal into the existing `Classification` domain model.
  - `route`: choose the best owner/team and produce the existing `Route` domain model.
- The existing React UI/API contract is unchanged. UI reads still come from FastAPI projections over `signals`, `classifications`, and `routes`.
- Manual listening profile seeding is the current setup path. Guided onboarding/listening setup is deferred for the next iteration.

## Working Flow

```text
Manual ListeningProfile seed
-> sync_public_listening
-> Apify actor
-> normalize_apify_item
-> process_signal
-> SignalTriageAgent via AgentRuntime/LangGraph
-> OpenRouter classify call
-> OpenRouter route call when actionable
-> record signal/classification/route
-> record llm_calls and agent_sessions/agent_steps
-> FastAPI projections
-> React UI
```

For off-brand or ignored classifications, the triage agent does not call the route model. It routes to `(none)` with `matched_rule="ignored_by_classifier"`.

For low-confidence classification or invalid/low-confidence route output, the route falls back to the review queue.

## Key Files

- `src/resound/social/apify.py`: Apify REST client and source-specific actor input.
- `src/resound/social/__init__.py`: source types, actor IDs, and Apify item normalization.
- `src/resound/workflows/public_listening.py`: Apify-backed public-listening sync.
- `src/resound/workflows/signal_processing.py`: records signals and now defaults to agentic triage.
- `src/resound/agents/signal_triage.py`: LangGraph-backed classification and routing orchestration.
- `src/resound/agents/team_directory.py`: generic plus brand-specific owner/team directory.
- `src/resound/prompts/route.py`: routing-agent prompt.
- `src/resound/prompts/classify.py`: classification prompt.
- `src/resound/classifiers/openrouter.py`: classification response parsing helper.
- `config/models.yaml`: global model stages including `classify` and `route`.
- `brands/notion/models.yaml`: cheap Notion smoke-test model override.
- `src/resound/cli.py`: local `sync-public-listening` command for manual seeding and sync.

## Current Local Commands

Run a bounded agentic sync against a fresh/local SQLite database:

```bash
RESOUND_DATABASE_URL=sqlite:///./data/resound-agentic-demo.db uv run resound sync-public-listening --brand notion --organization demo --source reddit --max-items 1
```

Use a larger cap to populate more UI rows:

```bash
RESOUND_DATABASE_URL=sqlite:///./data/resound-agentic-demo.db uv run resound sync-public-listening --brand notion --organization demo --source reddit --max-items 10
```

Start the backend against the agentic demo DB:

```bash
RESOUND_DATABASE_URL=sqlite:///./data/resound-agentic-demo.db RESOUND_CORS_ORIGINS=http://127.0.0.1:5004,http://localhost:5004 uv run resound api --host 127.0.0.1 --port 8004
```

Start the frontend from `Resound-UI/Builtiful-Interface/`:

```bash
PORT=5004 BASE_PATH=/ VITE_API_BASE_URL=http://127.0.0.1:8004 pnpm --filter @workspace/resound run dev
```

On Windows `cmd.exe`, use:

```cmd
set PORT=5004&& set BASE_PATH=/&& set VITE_API_BASE_URL=http://127.0.0.1:8004&& pnpm --filter @workspace/resound run dev
```

## Proven Live Results

### Apify Agentic Smoke

Command shape:

```bash
RESOUND_DATABASE_URL=sqlite:///./data/resound-agentic-demo.db uv run resound sync-public-listening --brand notion --organization demo --source reddit --max-items 1
```

Observed result:

```text
completed processed=1 skipped=0 synced=['reddit']
```

Persisted proof from `data/resound-agentic-demo.db`:

- `routes`: owner selected by agent, `matched_rule="agent_route"`.
- `llm_calls`: `classify` and `route` success rows.
- `agent_sessions`: `signal_triage`, `completed`.
- `agent_steps`: `classify_signal`, `route_signal`.

### Off-Brand Safety Smoke

Another one-item Apify run returned an off-brand Reddit result. The classifier correctly marked it off-brand and the route stage short-circuited:

- classification: `is_about_brand=false`, `action_class=ignore`.
- route: `(none)`, `matched_rule="ignored_by_classifier"`.
- `llm_calls`: only `classify`, no route-model call.
- agent session still completed with classify and route bookkeeping steps.

### Crafted Route Smoke

A crafted Notion signal was processed through `process_signal` to exercise both model calls:

```text
Notion AI is failing to sync project databases and our team cannot ship client work today.
```

Observed persisted result:

- classification: `engineering`, `critical`, `immediate`.
- route: `#incident-comms`, `matched_rule="agent_route"`, `priority=immediate`.
- `llm_calls`: `classify` via Notion override and `route` via global route stage.
- `agent_sessions`: `signal_triage`, `completed`.
- `agent_steps`: `classify_signal`, `route_signal`.

## Verification Run

Current backend verification passed after the agentic changes:

```text
uv run python -m compileall src/resound
uv run pytest --basetemp "C:\Users\Ananthapadmanabha\AppData\Local\Temp\opencode\pytest-agentic-full-2"
uv run ruff check src/resound/api src/resound/memory/__init__.py src/resound/cli.py tests/api/test_api.py
```

Result:

```text
171 passed
```

Additional focused tests cover:

- team-directory merging and default owners.
- classification plus route agent happy path.
- invalid route owner fallback.
- actionable `(none)` route rejection.
- off-brand route short-circuit.
- low classification confidence fallback to review.
- route gateway failure fallback and LLM failure audit row.
- public-listening sync using agentic triage when no legacy classifier is injected.
- fatal LLM config/auth errors re-raising from source sync.
- retrying a raw-only partial signal row instead of permanently treating it as a duplicate.

## What Is Working

- Apify Reddit actor `solidcode/reddit-scraper` works through the local CLI path.
- Apify auth uses bearer headers, not token query params.
- Fresh SQLite demo DBs work without the stale `data/resound.db` schema issue.
- FastAPI read endpoints populate the current React UI from agentic DB rows.
- Agentic classification/routing stores the same domain models the UI already expects.
- Agent sessions and steps are persisted for traceability.
- LLM cost/latency/failure audit still flows through `llm_calls`.

## Important Caveats

- The currently launched UI may show only one signal because `data/resound-agentic-demo.db` was populated with `--max-items 1` for cost control. Run a larger sync to populate more rows.
- Only Reddit has been live-validated through Apify. Instagram, TikTok, YouTube comments, and X still need source-specific input/output validation.
- The live proof used the CLI/direct workflow function, not a full Temporal API plus worker round trip.
- `POST /api/workflows/source-sync` is wired for Temporal, but the end-to-end Temporal worker path still needs a live smoke test.
- Listening setup/onboarding currently creates pending suggestions and is not the production setup path yet.
- The legacy synchronous `Pipeline` path still exists and still uses the legacy classifier/router pattern. The public-listening workflow path is the current agentic backend path.
- Generic team defaults are in code for now. Onboarding should eventually persist or configure organization-specific team directories.

## Next Improvements

1. Populate `data/resound-agentic-demo.db` with more Notion rows using `--max-items 10` or `--max-items 25`, then visually inspect the UI.
2. Run the full Temporal path locally: start Temporal, API, worker, seed profile, call `POST /api/workflows/source-sync`, and verify workflow/job/event rows.
3. Validate additional Apify sources one at a time with source-specific inputs and normalization.
4. Promote generic team setup into a configurable/default team directory rather than code-only defaults.
5. Wire onboarding/listening setup so approved suggestions create the listening profile and team context automatically.
6. Add routing quality evaluation using feedback events and route correctness metrics.
7. Decide final demo model profile for Notion, including whether to switch `classify` to Sonnet 5 for the final refresh.
8. Add browser automation or manual screenshot evidence once Playwright/browser tooling is available.

## Current Mental Model

Resound now has two separate concerns:

- Setup/onboarding decides what to listen to and what teams exist.
- Public listening sync ingests data and runs agentic classification plus routing.

For now, setup is manual and sync is agentic. The next major product step is to make setup agentic and durable too, then feed its approved output into the already-working public-listening agent path.
