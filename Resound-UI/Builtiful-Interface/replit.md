# Resound UI

Production React interface for the Resound memory/API backend.

## Run & Operate

- Backend API: from the repo root, run `uv run resound api --host 127.0.0.1 --port 8000`
- Frontend dev: run `PORT=5000 BASE_PATH=/ VITE_API_BASE_URL=http://127.0.0.1:8000 pnpm --filter @workspace/resound run dev`
- `pnpm run typecheck` — full typecheck across all packages
- `PORT=5000 BASE_PATH=/ pnpm --filter @workspace/resound run build` — build the production UI
- From the repo root, run `uv run resound export-openapi`, then in this workspace run `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from FastAPI
- Required backend env: `RESOUND_DATABASE_URL`, `RESOUND_CORS_ORIGINS`

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: FastAPI in `src/resound/api/` from the repo root
- DB: SQLAlchemy `SqlMemory` over SQLite dev / Postgres production
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- React app: `artifacts/resound/src/`
- Backend API: `src/resound/api/`
- API client: `lib/api-client-react/`
- Finalized UI data adapter: `artifacts/resound/src/api/viewModels.ts`

## Architecture decisions

- FastAPI is the production API. The Express scaffold remains generated collateral for now.
- The React UI uses generated API hooks plus a view-model adapter so backend DTOs do not leak into visual components.
- Reroute is modeled as an append-only team handoff event; the current owner is a projection.

## Product

Operators can inspect brand signal health, browse routed customer voice, review memory, submit feedback, and move routed signals between teams.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

_Populate as you build — sharp edges, "always run X before Y" rules._

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
