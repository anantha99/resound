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
- `RESOUND_TEMPORAL_ADDRESS`: Temporal frontend address.
- `RESOUND_TEMPORAL_NAMESPACE`: Temporal namespace, usually `default` locally.
- `RESOUND_TEMPORAL_TASK_QUEUE`: worker task queue, default `resound-default`.
- `RESOUND_REQUIRE_TENANT_HEADER=true`: require tenant headers in production.
- `OPENROUTER_API_KEY`: required before LLM-backed classification or reports run.

## Deployment Order

1. Start Postgres and Temporal.
2. Run `uv run alembic upgrade head` against the production database.
3. Start one or more API processes.
4. Start one or more Temporal worker processes on the configured task queue.
5. Check `/api/healthz`, then submit a source-sync command and verify a workflow job row appears.

## Common Failures

- Database connection failure: verify `RESOUND_DATABASE_URL`, security groups, and migration job logs.
- Temporal connection failure: verify `RESOUND_TEMPORAL_ADDRESS`, namespace, and task queue.
- LLM failures: verify `OPENROUTER_API_KEY`; inspect `llm_calls` and workflow events.
- Tenant access failures: verify `X-Resound-Organization` is present and maps to an organization row.
