# Codex Instructions

## Task Master AI Instructions
**Import Task Master's development workflow commands and guidelines, treat as if import is in the main AGENTS.md file.**
@./.taskmaster/CLAUDE.md

## Product Structure

Resound is now a Python FastAPI backend with a React frontend workspace checked into the repo.

- Backend package: `src/resound/`
- FastAPI app: `src/resound/api/app.py`
- API DTOs/projections/routes: `src/resound/api/`
- Memory and persistence layer: `src/resound/memory/`
- Brand bundles: `brands/<slug>/`
- Default frontend workspace: `Resound-UI/Builtiful-Interface/`
- Default React app: `Resound-UI/Builtiful-Interface/artifacts/resound/`
- Generated React API client: `Resound-UI/Builtiful-Interface/lib/api-client-react/`
- OpenAPI source file for frontend codegen: `Resound-UI/Builtiful-Interface/lib/api-spec/openapi.yaml`

The frontend workspace also contains generated collateral from the UI export, including `artifacts/mockup-sandbox/`, `artifacts/api-server/`, `lib/db/`, and `lib/api-zod/`. Treat `artifacts/resound/` as the production/default UI.

## Run Commands

Start the backend from the repo root:

```bash
uv run resound api --host 127.0.0.1 --port 8000
```

Start the frontend from `Resound-UI/Builtiful-Interface/`:

```bash
PORT=5000 BASE_PATH=/ VITE_API_BASE_URL=http://127.0.0.1:8000 pnpm --filter @workspace/resound run dev
```

Windows `cmd.exe` equivalent from `Resound-UI\Builtiful-Interface`:

```cmd
set PORT=5000&& set BASE_PATH=/&& set VITE_API_BASE_URL=http://127.0.0.1:8000&& pnpm --filter @workspace/resound run dev
```

Build the production frontend from `Resound-UI/Builtiful-Interface/`:

```bash
PORT=5000 BASE_PATH=/ pnpm --filter @workspace/resound run build
```

## API Contract Workflow

FastAPI is the source of truth for the browser/mobile API contract.

Regenerate the checked-in OpenAPI file from the repo root:

```bash
uv run resound export-openapi
```

Then regenerate the TypeScript clients from `Resound-UI/Builtiful-Interface/`:

```bash
pnpm --filter @workspace/api-spec run codegen
```

The runtime backend exposes both `/api` and `/api/v1`. The exported frontend schema intentionally strips the `/api` prefix and excludes `/api/v1` duplicates because the Orval client already uses `/api` as its base path.

## Current Progress

- The FastAPI backend is connected to the production React UI through generated React Query hooks and `artifacts/resound/src/api/viewModels.ts`.
- The default UI shows backend brands `liquiddeath`, `fulfil`, and `ridge`, plus demo brand bundles `oatly` and `notion`.
- Local `liquiddeath` data is available through `data/resound.db`; other brands may show empty states until data is ingested or seeded.
- Reroute is modeled as an append-only route handoff and projected as the current owner.
- Feedback submission records route feedback through the backend.
- `Resound-UI.zip`, `node_modules/`, `.local/`, and runtime `data/` directories stay ignored; the extracted frontend source tree is intended to be tracked.

## Verification Commands

Use these checks before shipping backend/frontend integration changes:

```bash
uv run python -m compileall src/resound
uv run pytest --basetemp "C:\Users\Ananthapadmanabha\AppData\Local\Temp\opencode\pytest-all"
uv run ruff check src/resound/api src/resound/memory/__init__.py src/resound/cli.py tests/api/test_api.py
```

From `Resound-UI/Builtiful-Interface/`:

```bash
pnpm run typecheck
PORT=5000 BASE_PATH=/ pnpm --filter @workspace/resound run build
```

Browser screenshot tooling is not currently installed in this environment, so manual browser smoke testing is still required for visual verification.
