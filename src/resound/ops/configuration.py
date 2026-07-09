"""Production configuration validation helpers."""

from __future__ import annotations

from resound.config import env


def runtime_configuration_status() -> dict[str, str]:
    database_url = env("RESOUND_DATABASE_URL")
    temporal_address = env("RESOUND_TEMPORAL_ADDRESS")
    openrouter_key = env("OPENROUTER_API_KEY")
    return {
        "database": "configured" if database_url else "missing",
        "temporal": "configured" if temporal_address else "missing",
        "openrouter": "configured" if openrouter_key else "missing",
    }
