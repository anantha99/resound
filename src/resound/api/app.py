from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from resound.api import schemas
from resound.api.routes import brands, health, patterns, routes, signals
from resound.config import env


def create_app() -> FastAPI:
    app = FastAPI(
        title="Api",
        version="0.1.0",
        description="Resound customer signal intelligence API",
    )

    origins = _cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    for prefix, include_in_schema in (("/api", True), ("/api/v1", False)):
        app.include_router(health.router, prefix=prefix, include_in_schema=include_in_schema)
        app.include_router(brands.router, prefix=prefix, include_in_schema=include_in_schema)
        app.include_router(signals.router, prefix=prefix, include_in_schema=include_in_schema)
        app.include_router(routes.router, prefix=prefix, include_in_schema=include_in_schema)
        app.include_router(patterns.router, prefix=prefix, include_in_schema=include_in_schema)

    @app.exception_handler(Exception)
    async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
        problem = schemas.Problem(
            title="Internal Server Error",
            status=500,
            detail=str(exc),
        )
        return JSONResponse(status_code=500, content=problem.model_dump(by_alias=True))

    return app


def _cors_origins() -> list[str]:
    raw = env("RESOUND_CORS_ORIGINS")
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [
        "http://localhost:5173",
        "http://localhost:5000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5000",
    ]


app = create_app()
