"""Immutable contracts for approved public-listening source execution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import core_schema


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


class FrozenDict(Mapping[str, Any]):
    """Small recursively immutable mapping used for behavior-bearing JSON."""

    def __init__(self, value: Mapping[str, Any]):
        self._data = {str(key): deep_freeze(item) for key, item in value.items()}

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(self._data)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            lambda value: value if isinstance(value, cls) else cls(value),
            core_schema.dict_schema(core_schema.str_schema(), core_schema.any_schema()),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: _canonical_value(value)
            ),
        )


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenDict(value)
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    return value


class PublicSource(StrEnum):
    REDDIT = "reddit"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    X = "x"
    YOUTUBE = "youtube"


class SourcePath(StrEnum):
    OFFICIAL_DISCOVERY = "official_discovery"
    MENTION_DISCOVERY = "mention_discovery"
    OFFICIAL_COMMENTS = "official_comments"
    MENTION_COMMENTS = "mention_comments"


CANONICAL_SOURCE_ORDER = ("reddit", "instagram", "tiktok", "x", "youtube")
CANONICAL_PATH_ORDER = tuple(path.value for path in SourcePath)
SOURCE_ALIASES = {
    "reddit": "reddit",
    "instagram": "instagram",
    "instagram_public": "instagram",
    "tiktok": "tiktok",
    "x": "x",
    "x_public": "x",
    "twitter": "x",
    "youtube": "youtube",
    "youtube_comments": "youtube",
}


def canonical_json(value: Any) -> str:
    """Serialize behavior-bearing values deterministically for fingerprints."""

    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def sha256_value(value: Any) -> str:
    payload = value if isinstance(value, str) else canonical_json(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {
            name: _canonical_value(getattr(value, name)) for name in value.__class__.model_fields
        }
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


class ApprovedSourceConfigFingerprint(FrozenModel):
    algorithm: Literal["sha256"] = "sha256"
    value: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_envelope_value: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_version: str


class ResolvedProviderEvidence(FrozenModel):
    actor_id: str
    build_id: str
    build_number: str
    provider_declared_input_schema_reference: str
    provider_declared_input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_declared_output_schema_reference: str | None = None
    provider_declared_output_schema_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    fixture_derived_shape_reference: str
    fixture_derived_shape_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canary_required: bool
    canary_evidence_reference: str | None = None
    canary_evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    charge_quantum_usd: Decimal
    minimum_call_charge_usd: Decimal
    conservative_request_cost_usd: Decimal

    @model_validator(mode="after")
    def validate_canary_and_costs(self) -> ResolvedProviderEvidence:
        if self.canary_required and not (
            self.canary_evidence_reference and self.canary_evidence_sha256
        ):
            raise ValueError("passing canary evidence is required without a formal output schema")
        if not self.provider_declared_output_schema_reference and not self.canary_required:
            raise ValueError("actors without a formal output schema must require a canary")
        if bool(self.provider_declared_output_schema_reference) != bool(
            self.provider_declared_output_schema_sha256
        ):
            raise ValueError("formal output schema reference and hash must be supplied together")
        if any(
            value <= 0
            for value in (
                self.charge_quantum_usd,
                self.minimum_call_charge_usd,
                self.conservative_request_cost_usd,
            )
        ):
            raise ValueError("provider pricing values must be greater than zero")
        return self


class ProviderEvidenceRecord(FrozenModel):
    """Truthful manifest evidence, including intentionally incomplete captures."""

    actor_id: str
    build_id: str
    build_number: str
    captured_at: str | None = None
    path: SourcePath
    sanitized_input: dict[str, Any]
    input_url_shape: Literal["string", "request_object", "none"]
    provider_declared_input_schema_reference: str
    provider_declared_input_schema_sha256: str | None = None
    provider_declared_input_schema_sha256_prefix: str | None = None
    provider_declared_output_schema_reference: str | None = None
    provider_declared_output_schema_sha256: str | None = None
    provider_declared_output_schema_sha256_prefix: str | None = None
    fixture_path: str | None = None
    fixture_sha256: str | None = None
    fixture_derived_shape_reference: str | None = None
    fixture_derived_shape_sha256: str | None = None
    charge_quantum_usd: Decimal | None = None
    minimum_call_charge_usd: Decimal | None = None
    conservative_request_cost_usd: Decimal | None = None
    pricing_evidence_reference: str | None = None
    canary_required: bool
    canary_evidence_reference: str | None = None
    canary_evidence_sha256: str | None = None

    @property
    def approval_ready(self) -> bool:
        input_ready = self.provider_declared_input_schema_sha256 is not None
        output_or_canary = (
            self.provider_declared_output_schema_sha256 is not None
            or (
                self.canary_required
                and self.canary_evidence_reference is not None
                and self.canary_evidence_sha256 is not None
            )
        )
        return bool(
            input_ready
            and output_or_canary
            and self.fixture_path
            and self.fixture_sha256
            and self.fixture_derived_shape_reference
            and self.fixture_derived_shape_sha256
            and self.charge_quantum_usd
            and self.minimum_call_charge_usd
            and self.conservative_request_cost_usd
            and self.pricing_evidence_reference
        )


class ProviderEvidenceManifest(FrozenModel):
    manifest_version: str
    entries: tuple[ProviderEvidenceRecord, ...]


class ResolvedPathConfig(FrozenModel):
    path: SourcePath
    enabled: bool = True
    selectors: tuple[str, ...] = ()
    actor_input_mode: str
    max_items: int
    max_parents: int = 0
    max_comments_per_parent: int = 0
    max_comments: int = 0
    requested_row_maximum: int
    derived_run_count: int


class ResolvedProcessingConfigSnapshot(FrozenModel):
    brand_context: str
    routing_config: FrozenDict
    people_config: FrozenDict
    model_profile: str | None = None
    brand_context_sha256: str
    routing_config_sha256: str
    people_config_sha256: str
    model_profile_sha256: str
    processing_sha256: str

    @classmethod
    def create(
        cls,
        *,
        brand_context: str,
        routing_config: dict[str, Any],
        people_config: dict[str, Any],
        model_profile: str | None,
    ) -> ResolvedProcessingConfigSnapshot:
        _validate_processing_value("brand_context", brand_context, 16 * 1024)
        _validate_processing_value("routing_config", routing_config, 64 * 1024)
        _validate_processing_value("people_config", people_config, 64 * 1024)
        if model_profile is not None:
            import re

            if len(model_profile) > 128:
                raise ValueError("model_profile exceeds 128 characters")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", model_profile):
                raise ValueError("model_profile must be a canonical profile key")
            lowered = model_profile.lower()
            if lowered.startswith("sk-") or "api_key" in lowered or "token" in lowered:
                raise ValueError("model_profile must not contain a credential or secret value")
        hashes = {
            "brand_context_sha256": sha256_value(brand_context),
            "routing_config_sha256": sha256_value(routing_config),
            "people_config_sha256": sha256_value(people_config),
            "model_profile_sha256": sha256_value(model_profile),
        }
        return cls(
            brand_context=brand_context,
            routing_config=FrozenDict(routing_config),
            people_config=FrozenDict(people_config),
            model_profile=model_profile,
            **hashes,
            processing_sha256=sha256_value(hashes),
        )


def _validate_processing_value(name: str, value: Any, byte_limit: int) -> None:
    serialized = value if isinstance(value, str) else canonical_json(value)
    if len(serialized.encode("utf-8")) > byte_limit:
        raise ValueError(f"{name} exceeds {byte_limit} UTF-8 bytes")
    if not isinstance(value, str):
        entries = 0

        def visit(item: Any, depth: int) -> None:
            nonlocal entries
            if depth > 8:
                raise ValueError(f"{name} exceeds maximum depth 8")
            if isinstance(item, dict):
                entries += len(item)
                for child in item.values():
                    visit(child, depth + 1)
            elif isinstance(item, list):
                entries += len(item)
                for child in item:
                    visit(child, depth + 1)
            if entries > 1000:
                raise ValueError(f"{name} exceeds 1000 mapping/list entries")

        visit(value, 1)


class AdapterLimits(FrozenModel):
    max_signals_per_source: int = 100
    max_items_per_path: int = 25
    max_parents_per_path: int = 10
    max_comments_per_parent: int = 5
    max_comments_per_path: int = 25
    max_comments_per_source: int = 50
    max_runs_per_source: int = 10
    max_cost_usd_per_source: Decimal = Decimal("1.00")
    page_size: int = 100
    deadline_reserve_seconds: int = 30

    @field_validator("*", mode="after")
    @classmethod
    def positive_limits(cls, value: Any) -> Any:
        if isinstance(value, (int, Decimal)) and value <= 0:
            raise ValueError("all adapter limits must be greater than zero")
        return value


class SourceLimitOverrides(FrozenModel):
    max_signals_per_source: int | None = None
    max_items_per_path: int | None = None
    max_parents_per_path: int | None = None
    max_comments_per_parent: int | None = None
    max_comments_per_path: int | None = None
    max_comments_per_source: int | None = None
    max_runs_per_source: int | None = None
    max_cost_usd_per_source: Decimal | None = None

    @field_validator("*", mode="after")
    @classmethod
    def positive_overrides(cls, value: Any) -> Any:
        if value is not None and value <= 0:
            raise ValueError("limit overrides must be greater than zero")
        return value


class SelectedPathInput(FrozenModel):
    source: str
    paths: tuple[str, ...]


class SourceSyncInput(FrozenModel):
    # API brand_id is historically a slug. Keep that wire name and separate DB identity.
    brand_id: str
    internal_brand_id: int | None = None
    selected_sources: tuple[str, ...] | None = None
    selected_paths: tuple[SelectedPathInput, ...] | None = None
    limits: SourceLimitOverrides = Field(default_factory=SourceLimitOverrides)


class ResolvedSourceConfigSnapshot(FrozenModel):
    source: PublicSource
    storage_platform: str
    paths: tuple[ResolvedPathConfig, ...]
    provider_evidence: tuple[ResolvedProviderEvidence, ...]
    limits: AdapterLimits
    processing: ResolvedProcessingConfigSnapshot
    approval_fingerprint: ApprovedSourceConfigFingerprint


class ResolvedPublicListeningRequest(FrozenModel):
    organization_id: int | None = None
    brand_id: int
    brand_slug: str
    workflow_job_id: int | None = None
    owner_token: str | None = None
    sources: tuple[ResolvedSourceConfigSnapshot, ...]
    selected_paths: dict[str, tuple[SourcePath, ...]]
    fingerprints: dict[str, ApprovedSourceConfigFingerprint]


class ProviderRunRef(FrozenModel):
    path: SourcePath
    actor_id: str
    build_id: str
    build_number: str
    run_id: str | None = None
    requested_row_maximum: int
    max_total_charge_usd: Decimal
    usage_total_usd: Decimal | None = None
    status: str
    input_schema_reference: str
    output_schema_reference: str | None = None
    fixture_shape_reference: str
    dataset_ids: tuple[str, ...] = ()


class ProviderDatasetRef(FrozenModel):
    path: SourcePath
    dataset_id: str
    run_id: str | None = None
    parent_identity_value: str | None = None
    requested_limit: int
    fetched_count: int
    processed_count: int
    provenance: dict[str, Any] = Field(default_factory=dict)


class AdapterIssue(FrozenModel):
    path: SourcePath | None = None
    code: str
    issue_class: str
    message: str = Field(max_length=1000)
    retryable: bool = False
    preserved_work: bool = False
    run_id: str | None = None
    dataset_id: str | None = None
    parent_identity_value: str | None = None


class CanonicalIdentity(FrozenModel):
    kind: Literal["provider_native_id", "fallback_identity_hash"]
    value: str


class SignalAssociation(FrozenModel):
    path: SourcePath
    identity: CanonicalIdentity
    signal_id: int | None = None
    parent_id: int | None = None
    processing_state: Literal["processed", "resumed", "duplicate", "skipped", "failed"]


class AdapterComponentResult(FrozenModel):
    path: SourcePath
    status: Literal["ok", "partial", "failed"]
    fetched_count: int = 0
    processed_count: int = 0
    resumed_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    cost_usd: Decimal = Decimal("0")
    runs: tuple[ProviderRunRef, ...] = ()
    datasets: tuple[ProviderDatasetRef, ...] = ()
    issues: tuple[AdapterIssue, ...] = ()
    associations: tuple[SignalAssociation, ...] = ()


class AdapterResult(FrozenModel):
    source: PublicSource
    platform: str
    status: Literal["ok", "partial", "failed"]
    paths: tuple[AdapterComponentResult, ...]
    max_signals_per_source: int
    fetched_count: int = 0
    processed_count: int = 0
    resumed_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    cost_usd: Decimal = Decimal("0")
    issues: tuple[AdapterIssue, ...] = ()
    cap_reached: bool = False
    config_fingerprint: ApprovedSourceConfigFingerprint


class PublicListeningSyncResult(FrozenModel):
    schema_version: Literal["1"] = "1"
    status: Literal["completed", "partial", "failed"]
    selected_sources: tuple[PublicSource, ...]
    selected_paths: dict[str, tuple[SourcePath, ...]]
    sources: tuple[AdapterResult, ...]
    effective_signal_caps: dict[str, int]
    fetched_count: int = 0
    processed_count: int = 0
    resumed_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    cost_usd: Decimal = Decimal("0")
    fingerprints: dict[str, ApprovedSourceConfigFingerprint]
    lease_outcome: str

