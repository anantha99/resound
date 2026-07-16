# Production Backend Runbook

Resound production runs separate API and worker processes over shared Postgres state.

For the current Apify plus LangGraph public-listening handoff, see
[`agentic-public-listening-progress.md`](agentic-public-listening-progress.md).

## Process Roles

- API: `uv run resound api --host 0.0.0.0 --port 8000`
- Temporal worker: `uv run resound worker`
- Migration job: `uv run alembic upgrade head`

## Required Configuration

- `RESOUND_DATABASE_URL`: Postgres URL, for example `postgresql+psycopg://...`
- `APIFY_API_TOKEN`: required for the bounded Reddit population runs.
- `APIFY_RUN_POLL_TIMEOUT_SECONDS`: optional actor completion timeout; defaults
  to `600` seconds and must remain below the 15-minute public-listening activity
  timeout so dataset processing has time to finish.
- `APIFY_RUN_POLL_INTERVAL_SECONDS`: optional initial actor status poll interval;
  defaults to `2` seconds and backs off exponentially to a 10-second maximum.
- `RESOUND_TEMPORAL_ADDRESS`: Temporal frontend address.
- `RESOUND_TEMPORAL_NAMESPACE`: Temporal namespace, usually `default` locally.
- `RESOUND_TEMPORAL_TASK_QUEUE`: worker task queue, default `resound-default`.
- `RESOUND_REQUIRE_TENANT_HEADER=true`: require tenant headers in production.
- `OPENROUTER_API_KEY`: required before LLM-backed classification or reports run.
- Frontend build variable `VITE_RESOUND_ORGANIZATION=demo`: sends
  `X-Resound-Organization: demo` on API requests. The recommended demo setup is
  to keep tenant enforcement enabled. Disabling `RESOUND_REQUIRE_TENANT_HEADER`
  is an explicit alternative only for an isolated demo backend.

Apify caps the synchronous actor-start wait at 60 seconds. A `RUNNING` start
response is expected for longer jobs: Resound polls `/v2/actor-runs/{run_id}`
until `SUCCEEDED` before reading the dataset. `FAILED`, `ABORTED`, and
`TIMED-OUT` runs fail that source without fetching a partial dataset.

## Deployment Order

1. Start Postgres and Temporal.
2. Run `uv run alembic upgrade head` against the production database.
3. Start one or more API processes.
4. Start one or more Temporal worker processes on the configured task queue.
5. Check `/api/healthz`, then submit a source-sync command and verify a workflow job row appears.

## Railway Liquid Death and Notion Demo Population

Run this procedure only from the approved release checkout, using the backend
service's Railway environment. Do not expand the brand or source lists: this
runbook covers Liquid Death (`liquiddeath`) and Notion (`notion`) over Reddit.

### 1. Deploy and check configuration

Deploy the backend first. Prefer remote execution from the deployed backend
image so the commands use its approved code/dependencies and can reach Railway
private networking:

1. Use a project-supported Railway job/one-off based on the deployed backend
   image, if configured. Run each command below as a separate job and retain
   its Railway logs.
2. Otherwise, open a remote shell in the active backend deployment. In the
   Railway dashboard, right-click the backend service and copy its SSH command,
   or use the equivalent linked-CLI command:

   ```bash
   railway ssh --service <backend-service> --environment <production-environment>
   ```

   `railway ssh` runs inside the deployed service container. Confirm the shell
   is for the intended project, production environment, and backend service
   before running anything.

In that remote job or SSH shell, check required variables without printing
their values:

```bash
uv run python - <<'PY'
import os

keys = [
    "RESOUND_DATABASE_URL",
    "APIFY_API_TOKEN",
    "OPENROUTER_API_KEY",
    "RESOUND_TEMPORAL_ADDRESS",
    "RESOUND_TEMPORAL_NAMESPACE",
    "RESOUND_TEMPORAL_TASK_QUEUE",
]
for key in keys:
    print(f"{key}: {'present' if os.getenv(key) else 'MISSING'}")
PY
```

Abort if any variable is `MISSING`. In the Railway frontend service, perform
the corresponding non-secret build-variable check:

```bash
node - <<'JS'
for (const key of ["VITE_API_BASE_URL", "VITE_RESOUND_ORGANIZATION"]) {
  console.log(`${key}: ${process.env[key] ? "present" : "MISSING"}`);
}
JS
```

`VITE_RESOUND_ORGANIZATION` must be set to `demo`, and the frontend must be
rebuilt/redeployed after it changes because Vite embeds it at build time.

### 2. Migrate, then verify API and worker health

Run migrations from the same remote backend execution context before starting
population:

```bash
uv run alembic upgrade head
```

Abort on any migration error. Confirm the deployed API returns success from
`$API/api/healthz`, and confirm the worker is connected to the configured
namespace/task queue in Railway logs. Do not start population while either
process is unhealthy.

```bash
curl -fsS "$API/api/healthz"
```

### 3. Capture bounded run logs

Run each command in the remote Railway job or `railway ssh` shell established
above. Prefer a Railway job because it provides a discrete exit status and
durable command log. For SSH execution, enable a local terminal transcript or
copy the complete command output into the deployment record; do not print or
record secret values. Keep migration, dry-run, smoke, and fill outputs as
separate artifacts with timestamps and the deployment identifier.

Do **not** treat `railway run` as a remote one-off. It executes on the local
machine and only injects variables from Railway. Use it only as an explicitly
approved fallback when remote jobs and `railway ssh` are unavailable, and only
from the approved release checkout with the locked dependencies installed:

```bash
railway run --service <backend-service> --environment <production-environment> -- \
  uv run resound populate-demo-brands <approved-options>
```

Before using that local fallback, confirm without printing values that the
injected `RESOUND_DATABASE_URL` and Temporal endpoints are externally
reachable from the local host. Railway private DNS/private-network addresses
will not work from `railway run`; in that case, abort rather than replacing
them with ad hoc credentials or endpoints. The same dry-run, log capture,
runtime, cost, and abort rules still apply.

First prove the plan is strictly non-mutating. A dry-run must make no database
writes and no Apify or OpenRouter calls:

```bash
uv run resound populate-demo-brands --organization demo --brand liquiddeath --brand notion --source reddit --max-items 10 --dry-run
```

Review its summary before continuing. Then run the one-item-per-brand smoke:

```bash
uv run resound populate-demo-brands --organization demo --brand notion --brand liquiddeath --source reddit --max-items 1 --strict
```

Only after the smoke and API checks below pass, run the bounded fill:

```bash
uv run resound populate-demo-brands --organization demo --brand liquiddeath --brand notion --source reddit --max-items 10 --strict
```

The routine fill remains capped at 10 items per source and brand. The CLI
enforces a hard maximum of 100, but that is a safety limit, not an approved
production target. The only approved increase in this procedure is the
single-brand 25-item recovery described after verification below. Do not run
commands concurrently for `demo`; a lock rejection means another population
is active and must be investigated rather than bypassed. Allow at most 20
minutes for the smoke and 30 minutes for the fill. Stop before further runs if
cumulative LLM telemetry for this procedure exceeds the approved operating
ceiling of $1 per 50 processed signals.

### 4. Model gate

The demo population profile must resolve to these exact OpenRouter models:

- Filter primary `google/gemini-3.1-flash-lite`; fallbacks
  `openai/gpt-5.4-nano`, then `anthropic/claude-haiku-4-5`.
- Classify primary `openai/gpt-5-mini`; reliability fallback
  `anthropic/claude-sonnet-5`; final fallback
  `google/gemini-3.1-flash-lite`.
- Route and routing-tiebreaker primary `google/gemini-3.1-flash-lite`;
  fallback `openai/gpt-5.4-nano`.
- Memory-query primary `google/gemini-3.1-flash-lite`; fallback
  `openai/gpt-5.4-nano`.

Do not use Notion's ordinary brand override or enable Liquid Death's commented
Opus override for this population. Abort if strict JSON parsing is not 100%
successful (including successful fallback), if fallback rate exceeds 10%, or
if the high-level area/severity/action classes are visibly wrong. If
`openai/gpt-5-mini` fails the classification gate, use the approved
`anthropic/claude-sonnet-5` reliability fallback for classification and record
the cost trade-off; do not silently accept malformed output. The CLI exposes
that live-fill choice explicitly as `--reliable-classifier`. It promotes
`anthropic/claude-sonnet-5` to classification primary, with
`openai/gpt-5-mini` then `google/gemini-3.1-flash-lite` as classification
fallbacks; filtering, routing, routing-tiebreaker, and memory-query models stay
unchanged.

Use this alternate fill command only after the semantic benchmark gate rejects
GPT-5 Mini, and retain its logs/cost comparison:

```bash
uv run resound populate-demo-brands --organization demo --brand liquiddeath --brand notion --source reddit --max-items 10 --strict --reliable-classifier
```

Do not add `--reliable-classifier` merely because a source returned no items;
empty-source recovery requires terms/subreddit inspection, not a classifier
change. If the failed 10-item fill already used the reliable classifier and a
targeted 25-item source recovery is approved below, keep the same option on the
recovery command so model selection does not change mid-comparison.

### 5. Verify persisted projections

Use the same tenant header as the frontend. Capture each response alongside
the population logs. Run all routes for both slugs (examples below show the
shell loop rather than silently checking Notion only):

```bash
mkdir -p demo-verification
curl -fsS -H 'X-Resound-Organization: demo' "$API/api/brands" \
  | tee demo-verification/brands.json

for brand in liquiddeath notion; do
  curl -fsS -H 'X-Resound-Organization: demo' "$API/api/brands/$brand/stats/7d" \
    | tee "demo-verification/$brand-stats.json"
  curl -fsS -H 'X-Resound-Organization: demo' "$API/api/signals?brandId=$brand&period=7d&limit=10" \
    | tee "demo-verification/$brand-signals.json"
  curl -fsS -H 'X-Resound-Organization: demo' "$API/api/patterns?brandId=$brand" \
    | tee "demo-verification/$brand-patterns.json"
  curl -fsS -H 'X-Resound-Organization: demo' "$API/api/routes?brandId=$brand&period=7d&limit=10" \
    | tee "demo-verification/$brand-routes.json"
  curl -fsS -H 'X-Resound-Organization: demo' "$API/api/source-health?brandId=$brand" \
    | tee "demo-verification/$brand-source-health.json"
  curl -fsS -H 'X-Resound-Organization: demo' "$API/api/telemetry/llm?brandId=$brand&period=7d" \
    | tee "demo-verification/$brand-llm.json"
  curl -fsS -H 'X-Resound-Organization: demo' "$API/api/evaluations/summary?brandId=$brand&period=7d" \
    | tee "demo-verification/$brand-evaluations.json"
done
```

After the smoke, require a non-zero processed count, non-zero `totalVolume`,
at least one route, useful Reddit source-health counts, successful LLM audit
rows, and a non-error evaluation response for each brand. Patterns may remain
empty with only one item, but must be usable after enough fill rows exist.
Apply the same checks after the fill.

If, and only if, the completed 10-item fill is still empty for exactly one
approved brand, inspect its persisted listening profile and the corresponding
`brands/<slug>/sources.yaml` Reddit search terms/subreddits. Broaden or correct
those source terms/subreddits deliberately, record the change and evidence,
then rerun only the affected `liquiddeath` or `notion` brand with a 25-item cap:

```bash
uv run resound populate-demo-brands --organization demo --brand <liquiddeath-or-notion> --source reddit --max-items 25 --strict
```

Append `--reliable-classifier` only when the preceding 10-item fill used that
approved reliable-classifier mode.

Do not use the recovery command for both brands, do not exceed 25 for demo
recovery, and do not rerun it repeatedly. Re-run all verification routes for
the targeted brand. If it still has zero processed signals, zero dashboard
volume, or no route rows, stop and report that brand as blocked with the source
configuration inspected, changes attempted, command/log identifiers, and API
verification evidence. Do not mask the empty result with synthetic data or an
unapproved higher cap.

Finally, open the deployed React UI and inspect browser network requests.
`/api/brands`, stats, signals, patterns, and routes must carry
`X-Resound-Organization: demo` and return without 401 responses. Verify the
brand picker and dashboard/signals/routes views for both Liquid Death and
Notion.

Abort immediately on missing environment, migration failure, unhealthy API or
worker, Apify/OpenRouter authentication failure, zero processed smoke results,
strict-JSON failure, fallback rate above 10%, the runtime/cost bounds above, or
tenant-header 401s. After the 10-item fill, zero dashboard volume or no routes
permits only the targeted 25-item recovery above; if recovery fails, report the
brand blocked and abort further population. Retain the Railway deployment
logs, migration output, all population command logs, and the API/browser
verification evidence. If a deployed-image Railway job and `railway ssh` are
both unavailable, and the explicitly approved local `railway run` fallback
cannot reach production dependencies, do not improvise a long-running service
command or expose private services; the protected demo-population API fallback
must be implemented first.

## Common Failures

- Database connection failure: verify `RESOUND_DATABASE_URL`, security groups, and migration job logs.
- Temporal connection failure: verify `RESOUND_TEMPORAL_ADDRESS`, namespace, and task queue.
- LLM failures: verify `OPENROUTER_API_KEY`; inspect `llm_calls` and workflow events.
- Tenant access failures: verify `X-Resound-Organization` is present and maps to an organization row.
