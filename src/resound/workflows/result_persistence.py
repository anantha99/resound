"""Independent bounds for durable public-listening requests and terminal results."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

MAX_SOURCES = 5
MAX_PATHS = 4
MAX_RUNS = 10
MAX_DATASETS = 25
MAX_ISSUES = 20
MAX_ASSOCIATIONS = 100
MAX_STRING = 1000


def bounded_request_snapshot(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    payload = _json_payload(value)
    sources = payload.get("sources", [])
    if not isinstance(sources, list) or len(sources) > MAX_SOURCES:
        raise ValueError("resolved request exceeds five sources")
    for source in sources:
        paths = source.get("paths", [])
        if not isinstance(paths, list) or len(paths) > MAX_PATHS:
            raise ValueError("resolved request exceeds four paths per source")
        processing = source.get("processing", {})
        _bounded_utf8(processing.get("brand_context", ""), 16 * 1024, "brand_context")
        _bounded_json(processing.get("routing_config", {}), 64 * 1024, "routing_config")
        _bounded_json(processing.get("people_config", {}), 64 * 1024, "people_config")
        model_profile = processing.get("model_profile")
        if model_profile is not None and len(str(model_profile)) > 128:
            raise ValueError("model_profile exceeds 128 characters")
    return payload


def bounded_result_summary(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    """Project schema v1 with deterministic collection and string truncation metadata."""

    payload = _json_payload(value)
    sources = list(payload.get("sources") or [])
    projected = _bounded_scalars(payload, excluded={"sources"})
    projected["schema_version"] = 1
    projected["sources_original_count"] = len(sources)
    projected["sources_truncated_count"] = max(0, len(sources) - MAX_SOURCES)
    projected["sources"] = [_bound_source(item) for item in sources[:MAX_SOURCES]]
    return projected


def _bound_source(source: Mapping[str, Any]) -> dict[str, Any]:
    paths = list(source.get("paths") or [])
    result = _bounded_scalars(source, excluded={"paths", "issues"})
    result.update(_bounded_collection("issues", source.get("issues"), MAX_ISSUES))
    result["paths_original_count"] = len(paths)
    result["paths_truncated_count"] = max(0, len(paths) - MAX_PATHS)
    result["paths"] = [_bound_path(item) for item in paths[:MAX_PATHS]]
    return result


def _bound_path(component: Mapping[str, Any]) -> dict[str, Any]:
    result = _bounded_scalars(
        component,
        excluded={"runs", "datasets", "issues", "associations"},
    )
    for name, limit in (
        ("runs", MAX_RUNS),
        ("datasets", MAX_DATASETS),
        ("issues", MAX_ISSUES),
        ("associations", MAX_ASSOCIATIONS),
    ):
        result.update(_bounded_collection(name, component.get(name), limit))
    return result


def _bounded_collection(name: str, value: Any, limit: int) -> dict[str, Any]:
    items = list(value or [])
    return {
        f"{name}_original_count": len(items),
        f"{name}_truncated_count": max(0, len(items) - limit),
        name: [_bound_value(item) for item in items[:limit]],
    }


def _bounded_scalars(value: Mapping[str, Any], *, excluded: set[str]) -> dict[str, Any]:
    return {key: _bound_value(item) for key, item in value.items() if key not in excluded}


def _bound_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, Mapping):
        return {str(key)[:128]: _bound_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_bound_value(item) for item in value]
    return value


def _json_payload(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return json.loads(json.dumps(dict(value), default=str))


def _bounded_utf8(value: Any, limit: int, name: str) -> None:
    if len(str(value).encode("utf-8")) > limit:
        raise ValueError(f"{name} exceeds {limit} UTF-8 bytes")


def _bounded_json(value: Any, limit: int, name: str) -> None:
    if len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > limit:
        raise ValueError(f"{name} exceeds {limit} UTF-8 bytes")
