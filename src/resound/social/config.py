"""Strict source configuration, aliases, capabilities, and approval envelopes."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from resound.social.contracts import (
    CANONICAL_PATH_ORDER,
    SOURCE_ALIASES,
    AdapterLimits,
    ResolvedProviderEvidence,
    canonical_json,
    sha256_value,
)

SOURCE_CONFIG_ALIASES = {
    "instagram_public": "instagram",
    "x_public": "x",
    "twitter": "x",
    "youtube_comments": "youtube",
}

SOURCE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "reddit": ("official_discovery", "mention_discovery"),
    "instagram": CANONICAL_PATH_ORDER,
    "tiktok": CANONICAL_PATH_ORDER,
    "x": ("official_discovery", "mention_discovery"),
    "youtube": ("official_discovery", "mention_discovery"),
}

CODE_CEILINGS = AdapterLimits()


class SourceConfigError(ValueError):
    """A source bundle is unsafe or cannot be represented truthfully."""


def canonical_source(value: str) -> str:
    normalized = value.strip().lower()
    try:
        return SOURCE_ALIASES[normalized]
    except KeyError as exc:
        raise SourceConfigError(f"unsupported public source: {value}") from exc


def normalize_source_mapping(sources: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_config in sources.items():
        if raw_key in {"g2"}:
            continue
        try:
            key = canonical_source(raw_key)
        except SourceConfigError:
            continue
        if key in normalized:
            raise SourceConfigError(
                f"duplicate source alias after normalization: {raw_key} -> {key}"
            )
        if not isinstance(raw_config, dict):
            raise SourceConfigError(f"source {raw_key} must be a mapping")
        normalized[key] = deepcopy(raw_config)
    return normalized


def normalize_selectors(source: str, config: dict[str, Any], path: str) -> tuple[str, ...]:
    if source == "instagram" and path == "mention_discovery":
        forbidden = ("search_terms", "caption_keywords", "keywords", "mention_terms")
        present = [key for key in forbidden if config.get(key)]
        if present:
            raise SourceConfigError(
                "Instagram does not support free-text mention terms; use hashtags or explicit "
                "public profile/place/user searches"
            )
        selectors: list[str] = []
        for key in (
            "hashtags",
            "public_profile_searches",
            "public_place_searches",
            "public_user_searches",
        ):
            selectors.extend(_string_list(config.get(key, []), key))
        if len(selectors) > 6:
            raise SourceConfigError("Instagram mention selectors exceed hard ceiling 6")
        return _dedupe(selectors)

    paths = config.get("paths", {})
    path_config = paths.get(path, {}) if isinstance(paths, dict) else {}
    configured = path_config.get("selectors") if isinstance(path_config, dict) else None
    if configured is None:
        if path.startswith("official"):
            configured = config.get("official_urls") or config.get("handles") or []
        else:
            configured = config.get("search_terms") or []
    selectors = _string_list(configured, f"{path}.selectors")
    if source == "instagram" and path == "official_discovery" and len(selectors) > 2:
        raise SourceConfigError("Instagram official selectors exceed hard ceiling 2")
    return _dedupe(selectors)


def selected_paths_for_config(source: str, config: dict[str, Any]) -> tuple[str, ...]:
    configured = config.get("paths")
    if not isinstance(configured, dict):
        return ("mention_discovery",)
    selected = tuple(
        path
        for path in SOURCE_CAPABILITIES[source]
        if isinstance(configured.get(path), dict) and configured[path].get("enabled", True)
    )
    return selected or ("mention_discovery",)


def approved_limits(config: dict[str, Any]) -> AdapterLimits:
    raw = config.get("limits", {})
    if not isinstance(raw, dict):
        raise SourceConfigError("source limits must be a mapping")
    try:
        return AdapterLimits.model_validate(raw)
    except ValueError as exc:
        raise SourceConfigError(f"invalid source limits: {exc}") from exc


def provider_evidence(config: dict[str, Any]) -> tuple[ResolvedProviderEvidence, ...]:
    raw = config.get("provider_evidence")
    values = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    if not values:
        raise SourceConfigError("approved source is missing provider_evidence")
    try:
        return tuple(ResolvedProviderEvidence.model_validate(value) for value in values)
    except ValueError as exc:
        raise SourceConfigError(f"invalid provider evidence: {exc}") from exc


def approval_envelope(config: dict[str, Any]) -> dict[str, Any]:
    envelope = deepcopy(config)
    envelope.pop("approved_envelope_fingerprint", None)
    envelope.pop("preflight_required", None)
    envelope.pop("enabled", None)
    return envelope


def approval_envelope_fingerprint(config: dict[str, Any]) -> str:
    return sha256_value(approval_envelope(config))


def verify_approval(source: str, config: dict[str, Any]) -> str:
    # Validate capabilities even for manually toggled configs.
    for path in selected_paths_for_config(source, config):
        normalize_selectors(source, config, path)
    if config.get("preflight_required") is not False:
        raise SourceConfigError(f"source {source} requires preflight")
    expected = approval_envelope_fingerprint(config)
    actual = config.get("approved_envelope_fingerprint")
    if actual != expected:
        raise SourceConfigError(
            f"source {source} approval fingerprint is missing or stale; manually clearing "
            "preflight_required does not approve execution"
        )
    provider_evidence(config)
    return expected


def canonical_config_copy(config: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through canonical JSON to detach YAML/database mutable objects."""

    import json

    return json.loads(canonical_json(config))


def _string_list(value: Any, name: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise SourceConfigError(f"{name} must be a string list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SourceConfigError(f"{name} contains an invalid selector")
        result.append(item.strip())
    return result


def _dedupe(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))

