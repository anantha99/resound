"""Shared lower-only request resolver for API and CLI callers."""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from resound.config import BrandConfig
from resound.social.common import allocate_signal_cap
from resound.social.config import (
    CODE_CEILINGS,
    SOURCE_CAPABILITIES,
    SourceConfigError,
    approved_limits,
    canonical_config_copy,
    canonical_source,
    normalize_selectors,
    normalize_source_mapping,
    provider_evidence,
    selected_paths_for_config,
    verify_approval,
)
from resound.social.contracts import (
    CANONICAL_PATH_ORDER,
    CANONICAL_SOURCE_ORDER,
    AdapterLimits,
    ApprovedSourceConfigFingerprint,
    ResolvedPathConfig,
    ResolvedProcessingConfigSnapshot,
    ResolvedPublicListeningRequest,
    ResolvedSelector,
    ResolvedSourceConfigSnapshot,
    SelectedPathInput,
    SourceLimitOverrides,
    SourcePath,
    SourceSyncInput,
    sha256_value,
)
from resound.social.registry import SOURCE_REGISTRY

ENV_LIMITS = {
    "max_signals_per_source": "RESOUND_SOCIAL_MAX_SIGNALS_PER_SOURCE",
    "max_items_per_path": "RESOUND_SOCIAL_MAX_ITEMS_PER_PATH",
    "max_parents_per_path": "RESOUND_SOCIAL_MAX_PARENTS_PER_PATH",
    "max_comments_per_parent": "RESOUND_SOCIAL_MAX_COMMENTS_PER_PARENT",
    "max_comments_per_path": "RESOUND_SOCIAL_MAX_COMMENTS_PER_PATH",
    "max_comments_per_source": "RESOUND_SOCIAL_MAX_COMMENTS_PER_SOURCE",
    "max_runs_per_source": "RESOUND_SOCIAL_MAX_RUNS_PER_SOURCE",
    "max_cost_usd_per_source": "RESOUND_SOCIAL_MAX_COST_USD_PER_SOURCE",
    "page_size": "RESOUND_SOCIAL_DATASET_PAGE_SIZE",
    "deadline_reserve_seconds": "RESOUND_SOCIAL_DEADLINE_RESERVE_SECONDS",
}


def resolve_public_listening_request(
    request: SourceSyncInput,
    *,
    brand_config: BrandConfig,
    memory: Any | None = None,
    organization_id: int | None = None,
    model_profile: str | None = None,
    workflow_job_id: int | None = None,
    owner_token: str | None = None,
    environment: dict[str, str] | None = None,
) -> ResolvedPublicListeningRequest:
    """Prove YAML approval, lower caps, refresh stale DB state, and freeze input."""

    sources = normalize_source_mapping(brand_config.sources)
    selected = _normalize_selected_sources(request.selected_sources)
    path_requests = _normalize_selected_paths(request.selected_paths, selected)
    processing = ResolvedProcessingConfigSnapshot.create(
        brand_context=brand_config.understanding,
        routing_config=brand_config.routing,
        people_config=brand_config.people,
        model_profile=model_profile,
    )
    approved: dict[str, str] = {}
    for source in selected:
        config = sources.get(source)
        if config is None:
            raise SourceConfigError(f"selected source {source} is not configured in brand YAML")
        if config.get("enabled") is not True:
            raise SourceConfigError(f"selected source {source} is disabled in brand YAML")
        approved[source] = verify_approval(source, config)

    # Never mutate runtime copies before every selected YAML source has proven approval.
    if memory is not None:
        if organization_id is None:
            raise ValueError("organization_id is required when refreshing database source copies")
        _refresh_stale_source_copy(
            memory,
            organization_id=organization_id,
            brand_id=_internal_brand_id(request),
            source_config=canonical_config_copy(brand_config.sources),
        )

    snapshots = []
    for source in selected:
        config = sources[source]
        limits = _resolve_limits(
            approved_limits(config), request.limits, environment=environment or os.environ
        )
        approved_paths = selected_paths_for_config(source, config)
        paths = path_requests.get(source) or approved_paths
        unapproved_paths = set(paths) - set(approved_paths)
        if unapproved_paths:
            raise SourceConfigError(
                f"request selected path(s) outside the approved YAML envelope: "
                f"{', '.join(sorted(unapproved_paths))}"
            )
        _validate_paths(source, paths)
        selectors = {path: normalize_selectors(source, config, path) for path in paths}
        missing_selectors = [
            path for path in paths if path.endswith("discovery") and not selectors[path]
        ]
        if missing_selectors:
            raise SourceConfigError(
                f"selected discovery path(s) have no selectors: {', '.join(missing_selectors)}"
            )
        base_caps = {
            path: limits.max_comments_per_path
            if path.endswith("comments")
            else limits.max_items_per_path
            for path in paths
        }
        comment_caps = {
            path: cap for path, cap in base_caps.items() if path.endswith("comments")
        }
        if comment_caps:
            comment_total = min(limits.max_comments_per_source, sum(comment_caps.values()))
            comment_allocations = allocate_signal_cap(comment_caps, comment_total)
            base_caps.update(comment_allocations)
        allocations = allocate_signal_cap(base_caps, limits.max_signals_per_source)
        path_configs = tuple(
            _resolve_path(source, path, selectors[path], limits, allocations[path])
            for path in CANONICAL_PATH_ORDER
            if path in paths
        )
        derived_runs = sum(item.derived_run_count for item in path_configs)
        if derived_runs > limits.max_runs_per_source:
            raise SourceConfigError(
                f"max_runs_per_source={limits.max_runs_per_source} is below derived Run "
                f"count {derived_runs} for {source}"
            )
        evidence = provider_evidence(source, config, paths)
        snapshot_body = {
            "source": source,
            "storage_platform": SOURCE_REGISTRY[source].storage_platform,
            "paths": path_configs,
            "provider_evidence": evidence,
            "limits": limits,
            "processing": processing,
            "approval_envelope_value": approved[source],
            "manifest_version": config.get("manifest_version", "1"),
        }
        fingerprint = ApprovedSourceConfigFingerprint(
            value=sha256_value(snapshot_body),
            approval_envelope_value=approved[source],
            manifest_version=str(config.get("manifest_version", "1")),
        )
        snapshots.append(
            ResolvedSourceConfigSnapshot(
                source=source,
                storage_platform=SOURCE_REGISTRY[source].storage_platform,
                paths=path_configs,
                provider_evidence=evidence,
                limits=limits,
                processing=processing,
                approval_fingerprint=fingerprint,
            )
        )
    return ResolvedPublicListeningRequest(
        organization_id=organization_id,
        brand_id=_internal_brand_id(request),
        brand_slug=brand_config.slug,
        workflow_job_id=workflow_job_id,
        owner_token=owner_token,
        sources=tuple(snapshots),
        selected_paths={
            snapshot.source.value: tuple(path.path for path in snapshot.paths)
            for snapshot in snapshots
        },
        fingerprints={
            snapshot.source.value: snapshot.approval_fingerprint for snapshot in snapshots
        },
    )


def parse_cli_request(
    *,
    brand_id: str,
    internal_brand_id: int | None = None,
    sources: list[str] | None,
    paths: list[str] | None,
    **limits: Any,
) -> SourceSyncInput:
    expanded_sources = tuple(
        source.strip()
        for value in sources or []
        for source in value.split(",")
        if source.strip()
    )
    selected_paths: list[SelectedPathInput] = []
    grouped: dict[str, list[str]] = {}
    for raw in paths or []:
        if ":" not in raw:
            raise SourceConfigError("--path must use SOURCE:PATH")
        source, path = raw.split(":", 1)
        grouped.setdefault(source, []).append(path)
    selected_paths.extend(
        SelectedPathInput(source=key, paths=tuple(value)) for key, value in grouped.items()
    )
    return SourceSyncInput(
        brand_id=brand_id,
        internal_brand_id=internal_brand_id,
        selected_sources=expanded_sources or None,
        selected_paths=tuple(selected_paths) if selected_paths else None,
        limits=SourceLimitOverrides.model_validate(
            {key: value for key, value in limits.items() if value is not None}
        ),
    )


def _internal_brand_id(request: SourceSyncInput) -> int:
    if request.internal_brand_id is None:
        raise SourceConfigError(
            "internal_brand_id must be resolved before workflow materialization"
        )
    return request.internal_brand_id


def _normalize_selected_sources(values: tuple[str, ...] | None) -> tuple[str, ...]:
    raw = values or ("reddit",)
    normalized = tuple(canonical_source(value) for value in raw)
    if len(set(normalized)) != len(normalized):
        raise SourceConfigError("duplicate source aliases are not allowed after normalization")
    return tuple(source for source in CANONICAL_SOURCE_ORDER if source in normalized)


def _normalize_selected_paths(
    values: tuple[SelectedPathInput, ...] | None,
    selected_sources: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for item in values or ():
        source = canonical_source(item.source)
        if source not in selected_sources:
            raise SourceConfigError(f"paths were supplied for unselected source {source}")
        if source in result:
            raise SourceConfigError(f"duplicate path source alias: {source}")
        if len(set(item.paths)) != len(item.paths):
            raise SourceConfigError(f"duplicate paths are not allowed for {source}")
        result[source] = tuple(path for path in CANONICAL_PATH_ORDER if path in item.paths)
        unknown = set(item.paths) - set(CANONICAL_PATH_ORDER)
        if unknown:
            raise SourceConfigError(
                f"unsupported path(s) for {source}: {', '.join(sorted(unknown))}"
            )
    return result


def _validate_paths(source: str, paths: tuple[str, ...]) -> None:
    unsupported = set(paths) - set(SOURCE_CAPABILITIES[source])
    if unsupported:
        raise SourceConfigError(
            f"source {source} does not support: {', '.join(sorted(unsupported))}"
        )
    for prefix in ("official", "mention"):
        if f"{prefix}_comments" in paths and f"{prefix}_discovery" not in paths:
            raise SourceConfigError(f"{prefix}_comments requires {prefix}_discovery")


def _resolve_limits(
    yaml_limits: AdapterLimits,
    overrides: SourceLimitOverrides,
    *,
    environment: dict[str, str],
) -> AdapterLimits:
    resolved: dict[str, int | Decimal] = {}
    override_values = overrides.model_dump()
    for field, code_value in CODE_CEILINGS.model_dump().items():
        yaml_value = getattr(yaml_limits, field)
        override = override_values.get(field)
        env_raw = environment.get(ENV_LIMITS[field])
        env_value = Decimal(env_raw) if isinstance(code_value, Decimal) and env_raw else (
            int(env_raw) if env_raw else code_value
        )
        candidates = [code_value, yaml_value, env_value]
        if override is not None:
            if override > min(candidates):
                raise SourceConfigError(
                    f"{field} override may only lower the approved and environment ceilings"
                )
            candidates.append(override)
        resolved[field] = min(candidates)
    return AdapterLimits.model_validate(resolved)


def _resolve_path(
    source: str,
    path: str,
    selectors: tuple[ResolvedSelector, ...],
    limits: AdapterLimits,
    allocation: int,
) -> ResolvedPathConfig:
    is_comment = path.endswith("comments")
    if source == "instagram" and path == "mention_discovery":
        runs = len(selectors)
        mode = "one_search_per_run"
    elif source == "tiktok" and is_comment:
        runs = 0
        mode = "comments_dataset"
    else:
        runs = 1
        mode = {
            "youtube": "request_object_start_urls",
            "instagram": "string_direct_urls",
        }.get(source, "string_urls")
    return ResolvedPathConfig(
        path=SourcePath(path),
        selectors=selectors,
        actor_input_mode=mode,
        max_items=0 if is_comment else allocation,
        max_parents=limits.max_parents_per_path if is_comment else 0,
        max_comments_per_parent=limits.max_comments_per_parent if is_comment else 0,
        max_comments=allocation if is_comment else 0,
        requested_row_maximum=allocation,
        derived_run_count=runs,
    )


def _refresh_stale_source_copy(
    memory: Any,
    *,
    organization_id: int,
    brand_id: int,
    source_config: dict[str, Any],
) -> None:
    if hasattr(memory, "replace_brand_source_config"):
        memory.replace_brand_source_config(organization_id, brand_id, source_config)
        return
    from sqlalchemy import select

    from resound.memory import BrandRow

    with memory.session() as session:
        row = session.execute(
            select(BrandRow).where(
                BrandRow.organization_id == organization_id,
                BrandRow.id == brand_id,
            )
        ).scalar_one_or_none()
        if row is None:
            raise SourceConfigError("brand row was not found for source config refresh")
        if row.source_config != source_config:
            row.source_config = source_config
            session.commit()
        session.refresh(row)
        if row.source_config != source_config:
            raise SourceConfigError(
                "database source config did not match approved YAML after refresh"
            )

