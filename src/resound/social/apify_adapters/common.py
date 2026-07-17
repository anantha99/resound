"""Shared immutable planning and strict parser helpers for Apify actors."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from resound.social.common import ProviderBudget, fallback_identity, provider_native_identity
from resound.social.contracts import CanonicalIdentity, SourcePath
from resound.social.registry import ActorRegistration


class AdapterBlockedError(RuntimeError):
    """The actor has no approved fixture/canary envelope and must not run."""


class ParserError(ValueError):
    """A provider row cannot produce a trustworthy normalized signal."""


class SelectorKind(StrEnum):
    """Wire-compatible selector kinds accepted from Task 1's resolved selector model."""

    URL = "url"
    HANDLE = "handle"
    SUBREDDIT = "subreddit"
    SEARCH = "search"
    HASHTAG = "hashtag"
    PROFILE = "profile"
    PLACE = "place"
    USER = "user"


@dataclass(frozen=True)
class TypedSelector:
    kind: SelectorKind
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SelectorKind(self.kind))
        object.__setattr__(self, "value", self.value.strip())
        if not self.value:
            raise ValueError("selector value cannot be empty")


@dataclass(frozen=True)
class ActorRunPlan:
    path: SourcePath
    actor: ActorRegistration
    actor_input: dict[str, Any]
    requested_row_maximum: int
    minimum_call_charge_usd: Decimal


@dataclass(frozen=True)
class ParentContext:
    platform: str
    content_kind: Literal["post", "video"]
    author_handle: str | None
    excerpt: str | None
    canonical_url: str
    published_at: datetime | None
    provider_native_id: str | None = None


@dataclass(frozen=True)
class DatasetFetchPlan:
    path: SourcePath
    dataset_id: str
    dataset_url: str
    requested_limit: int
    parent: ParentContext
    provenance: dict[str, str]


@dataclass(frozen=True)
class FetchedDataset:
    plan: DatasetFetchPlan
    items: tuple[dict[str, Any], ...]


def execute_dataset_fetch(client: Any, plan: DatasetFetchPlan, *, page_size: int) -> FetchedDataset:
    """Execute a bounded authenticated dataset GET without consuming an actor Run slot."""

    items = client.fetch_dataset_items(
        plan.dataset_id,
        dataset_url=plan.dataset_url,
        limit=plan.requested_limit,
        page_size=page_size,
    )
    return FetchedDataset(plan=plan, items=tuple(items))


@dataclass(frozen=True)
class AdapterPathPlan:
    path: SourcePath
    actor_runs: tuple[ActorRunPlan, ...] = ()
    dataset_fetches: tuple[DatasetFetchPlan, ...] = ()
    empty_reason: Literal["no_eligible_parents"] | None = None

    def __post_init__(self) -> None:
        if not self.actor_runs and not self.dataset_fetches and self.empty_reason is None:
            raise ValueError("path plan must contain work or an explicit empty reason")


class PathAdapter(Protocol):
    def plan_path(
        self,
        *,
        path: SourcePath,
        selectors: tuple[TypedSelector, ...] = (),
        parents: tuple[ParsedProviderSignal, ...] = (),
        item_cap: int,
        max_parents: int,
        max_comments_per_parent: int,
        max_comments: int,
    ) -> AdapterPathPlan: ...

    def parse_path_result(
        self,
        *,
        path: SourcePath,
        item: dict[str, Any],
        parent: ParentContext | None = None,
    ) -> ParsedProviderSignal: ...


@dataclass(frozen=True)
class ParsedProviderSignal:
    platform: str
    content_kind: Literal["post", "video", "comment"]
    identity: CanonicalIdentity
    content: str
    provider_timestamp: datetime
    canonical_url: str | None
    author_handle: str | None
    observed_public_metrics: dict[str, int] = dataclass_field(default_factory=dict)
    parent_context: ParentContext | None = None
    comments_dataset_url: str | None = None

    @property
    def parent_url(self) -> str | None:
        return self.parent_context.canonical_url if self.parent_context else None

    def as_parent_context(self) -> ParentContext:
        if self.content_kind not in {"post", "video"} or self.canonical_url is None:
            raise ValueError("only canonical posts/videos can be comment parents")
        native_id = self.identity.value if self.identity.kind == "provider_native_id" else None
        return ParentContext(
            platform=self.platform,
            content_kind=self.content_kind,
            author_handle=self.author_handle,
            excerpt=self.content[:500],
            canonical_url=self.canonical_url,
            published_at=self.provider_timestamp,
            provider_native_id=native_id,
        )

    def raw_metadata(self, path: SourcePath) -> dict[str, Any]:
        """Activity-facing safe metadata projection for persistence and API projection."""

        parent = self.parent_context
        return {
            "canonical_platform": self.platform,
            "content_kind": self.content_kind,
            "path": path.value,
            self.identity.kind: self.identity.value,
            "observed_public_metrics": dict(self.observed_public_metrics),
            "parent_context": (
                {
                    "platform": parent.platform,
                    "content_kind": parent.content_kind,
                    "author_handle": parent.author_handle,
                    "excerpt": parent.excerpt,
                    "url": parent.canonical_url,
                    "published_at": (
                        parent.published_at.isoformat() if parent.published_at is not None else None
                    ),
                    "provider_native_id": parent.provider_native_id,
                }
                if parent is not None
                else None
            ),
        }


@dataclass(frozen=True)
class ExecutedActorRun:
    path: SourcePath
    run: dict[str, Any]
    items: tuple[dict[str, Any], ...]
    usage_total_usd: Decimal


def actor_minimum_charge(actor: ActorRegistration) -> Decimal:
    """Return only captured actor-specific minimum evidence; Task 1 budget supplies the rest."""

    return actor.minimum_call_charge_usd or Decimal("0")


def execute_actor_run(
    client: Any,
    *,
    plan: ActorRunPlan,
    budget: ProviderBudget,
    reservation_id: str,
    page_size: int,
) -> ExecutedActorRun:
    """Execute one serial Run with Task 1's reservation and reconciliation invariants."""

    charge_cap = budget.remaining_charge_cap()
    if charge_cap < plan.minimum_call_charge_usd:
        raise RuntimeError("remaining provider budget is below the actor call minimum")
    run = client.run_actor(
        plan.actor.actor_id,
        plan.actor_input,
        build_number=plan.actor.build_number,
        expected_build_id=plan.actor.build_id,
        max_total_charge_usd=charge_cap,
        reservation_callback=lambda: budget.reserve(reservation_id),
    )
    completed = client.wait_for_run(run)
    raw_usage = completed.get("usageTotalUsd")
    try:
        usage = Decimal(str(raw_usage))
    except (DecimalException, ValueError) as exc:
        raise RuntimeError("terminal Apify Run has missing or malformed usageTotalUsd") from exc
    if not usage.is_finite() or usage < 0:
        raise RuntimeError("terminal Apify Run has missing or malformed usageTotalUsd")
    budget.reconcile(reservation_id, usage)
    dataset_id = completed.get("defaultDatasetId")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise RuntimeError("successful Apify Run is missing defaultDatasetId")
    items = client.fetch_dataset_items(
        dataset_id,
        limit=plan.requested_row_maximum,
        page_size=page_size,
    )
    return ExecutedActorRun(plan.path, completed, tuple(items), usage)


def require_approved(enabled: bool, source: str) -> None:
    if not enabled:
        raise AdapterBlockedError(
            f"{source} adapter is blocked until sanitized fixtures and required canary evidence "
            "are approved"
        )


def clean_strings(values: list[str] | tuple[str, ...], *, field: str) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field} must be a list of strings")
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a list of strings")
        normalized = value.strip()
        if normalized and normalized not in seen:
            cleaned.append(normalized)
            seen.add(normalized)
    return cleaned


def positive_quotient(total: int, selector_count: int, *, label: str) -> int:
    if total <= 0:
        raise ValueError(f"{label} cap must be greater than zero")
    if selector_count <= 0:
        raise ValueError(f"{label} requires at least one selector")
    quotient = total // selector_count
    if quotient <= 0:
        raise ValueError(f"{label} cap cannot allocate one row to every selector")
    return quotient


def exact_datetime(value: Any, *, field: str) -> datetime:
    if isinstance(value, bool) or value is None:
        raise ParserError(f"missing exact provider timestamp field {field}")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1_000_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise ParserError(f"invalid provider timestamp field {field}") from exc
    if not isinstance(value, str) or not value.strip():
        raise ParserError(f"missing exact provider timestamp field {field}")
    text = value.strip()
    if any(token in text.lower() for token in ("ago", "yesterday", "today", "just now")):
        raise ParserError(f"relative provider timestamp is not accepted for {field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ParserError(f"invalid provider timestamp field {field}") from exc
    if parsed.tzinfo is None:
        raise ParserError(f"provider timestamp field {field} must include a timezone")
    return parsed.astimezone(UTC)


def required_text(item: dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ParserError(f"missing non-empty provider content ({', '.join(fields)})")


def optional_text(item: dict[str, Any], *fields: str) -> str | None:
    for field in fields:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def canonical_http_url(value: Any, *, field: str, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ParserError(f"missing canonical URL field {field}")
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ParserError(f"invalid canonical URL field {field}")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ""))


def identity_for(
    *,
    native_id: Any,
    platform: str,
    content_kind: str,
    canonical_url: str | None,
    provider_timestamp: datetime,
    content: str,
) -> CanonicalIdentity:
    if isinstance(native_id, (str, int)) and not isinstance(native_id, bool):
        normalized = str(native_id).strip()
        if normalized:
            return provider_native_identity(normalized)
    if canonical_url is None:
        raise ParserError("provider row requires a native ID or complete canonical fallback fields")
    return fallback_identity(
        platform=platform,
        content_kind=content_kind,
        canonical_url=canonical_url,
        provider_timestamp=provider_timestamp,
        content=content,
    )


def nested_text(item: dict[str, Any], object_field: str, *fields: str) -> str | None:
    nested = item.get(object_field)
    if not isinstance(nested, dict):
        return None
    return optional_text(nested, *fields)


def observed_metrics(item: dict[str, Any], fields: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """Extract only non-negative, source-declared observed-public metric values."""

    result: dict[str, int] = {}
    for canonical_name, provider_fields in fields.items():
        for provider_field in provider_fields:
            value = item.get(provider_field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                continue
            result[canonical_name] = value
            break
    return result
