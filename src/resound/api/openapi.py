from __future__ import annotations

from copy import deepcopy
from typing import Any

from resound.api.app import app


def client_openapi_schema(
    *, source_prefix: str = "/api", server_url: str = "/api",
) -> dict[str, Any]:
    """Return the frontend-facing OpenAPI schema.

    The runtime app mounts routes under /api for browser compatibility. The
    generated React client already uses /api as its base URL, so exported paths
    must be prefix-free to avoid generating /api/api/... calls.
    """
    schema = deepcopy(app.openapi())
    schema["servers"] = [{"url": server_url, "description": "Base API path"}]
    schema["paths"] = _strip_path_prefix(schema.get("paths", {}), source_prefix)
    return schema


def _strip_path_prefix(paths: dict[str, Any], source_prefix: str) -> dict[str, Any]:
    normalized_prefix = source_prefix.rstrip("/")
    stripped_paths: dict[str, Any] = {}
    for path, config in paths.items():
        if not path.startswith(f"{normalized_prefix}/"):
            continue
        stripped = path[len(normalized_prefix):]
        if stripped.startswith("/v") and stripped.split("/", 2)[1][1:].isdigit():
            continue
        stripped_paths[stripped] = config
    return stripped_paths
