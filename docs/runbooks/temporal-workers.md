# Temporal Workers Runbook

Temporal owns durable execution for ingestion, signal processing, reports, and retention.

## Local Development

Run Temporal locally with Docker Compose:

```bash
docker compose up postgres temporal
```

Then run migrations and start separate roles:

```bash
uv run alembic upgrade head
uv run resound api --host 127.0.0.1 --port 8000
uv run resound worker
```

## Worker Scaling

- Scale API and worker processes independently.
- Keep `RESOUND_TEMPORAL_TASK_QUEUE` identical between API commands and workers.
- Add workers before increasing source sync cadence or report concurrency.

## Observability

- `workflow_jobs` records user/API command starts.
- `workflow_events` records stage transitions for dashboard reconstruction.
- `agent_sessions` and `agent_steps` record agent tool use.
- `llm_calls` remains the cost, fallback, latency, and error ledger.

## Recovery

- Retryable source/LLM failures should remain workflow-visible and retry in Temporal.
- Configuration/auth failures should fail loudly so operators can fix credentials.
- If a worker deploy is bad, stop the worker, roll back the image, and restart on the same task queue.
