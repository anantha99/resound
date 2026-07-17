"""Public listening sync workflow backed by Apify."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException
from typing import Any, Protocol

from resound.agents.signal_triage import SignalTriageAgent
from resound.core.classifier import Classifier
from resound.gateway import LLMGatewayAuthError, LLMGatewayConfigError
from resound.memory import SqlMemory
from resound.models import RawSignal
from resound.social import (
    AdapterComponentResult,
    AdapterIssue,
    AdapterResult,
    ListeningProfile,
    ProviderDatasetRef,
    ProviderRunRef,
    ResolvedPublicListeningRequest,
    ResolvedSourceConfigSnapshot,
    SignalAssociation,
    SourcePath,
    SourceType,
    build_apify_query_configs,
    get_source_adapter,
    normalize_apify_item,
)
from resound.social import (
    PublicListeningSyncResult as ResolvedPublicListeningSyncResult,
)
from resound.social.apify import ApifyClient, apify_actor_input
from resound.social.apify_adapters.common import (
    ActorRunPlan,
    AdapterBlockedError,
    AdapterPathPlan,
    ParentContext,
    ParsedProviderSignal,
    TypedSelector,
)
from resound.social.common import ProviderBudget, UnresolvedActorStartError
from resound.social.config import SourceConfigError
from resound.social.registry import ActorRegistration, actor_role_for_path
from resound.tenancy import TenantContext
from resound.workflows.leases import PUBLIC_LISTENING_WORKFLOW_KIND
from resound.workflows.signal_processing import (
    LeaseLostError,
    SignalProcessingRequest,
    process_signal,
    signal_processing_is_resume,
)
from resound.workflows.temporal_compat import activity, workflow


class PublicListeningClient(Protocol):
    def run_actor(self, actor_id: str, actor_input: dict): ...

    def wait_for_run(
        self,
        run: dict,
        *,
        progress_callback: Callable[[], None] | None = None,
    ) -> dict: ...

    def fetch_dataset_items(self, dataset_id: str) -> list[dict]: ...


class PublicListeningProgressError(RuntimeError):
    """Raised when a runtime progress hook cannot confirm continued ownership."""


@dataclass(frozen=True)
class PublicListeningSyncRequest:
    tenant: TenantContext
    brand_id: int
    brand_slug: str
    brand_context: str
    routing_config: dict
    people_config: dict
    workflow_job_id: int | None = None
    enabled_sources: list[SourceType] | None = None
    max_items_per_source: int = 100
    model_profile: str | None = None


@dataclass(frozen=True)
class PublicListeningSyncResult:
    status: str
    synced_sources: list[str]
    processed_count: int
    skipped_count: int
    failed_sources: dict[str, str]


def sync_public_listening(
    request: PublicListeningSyncRequest,
    *,
    memory: SqlMemory | None = None,
    apify_client: PublicListeningClient | None = None,
    classifier: Classifier | None = None,
    triage_agent: SignalTriageAgent | None = None,
    progress_callback: Callable[[], None] | None = None,
) -> PublicListeningSyncResult:
    memory = memory or SqlMemory()
    apify_client = apify_client or ApifyClient()
    if classifier is None and triage_agent is None:
        triage_agent = SignalTriageAgent(memory=memory)
    profile = memory.get_listening_profile(
        organization_id=request.tenant.organization_id,
        brand_id=request.brand_id,
        brand_slug=request.brand_slug,
    ) or ListeningProfile(brand_slug=request.brand_slug, brand_names=[request.brand_slug])
    configs = build_apify_query_configs(profile)
    if request.enabled_sources is not None:
        enabled_sources = set(request.enabled_sources)
        configs = [config for config in configs if config.source_type in enabled_sources]
    max_items_per_source = max(1, request.max_items_per_source)
    synced_sources: list[str] = []
    failed_sources: dict[str, str] = {}
    processed_count = 0
    skipped_count = 0
    checked_at = datetime.now(tz=UTC).replace(tzinfo=None)

    if request.workflow_job_id is not None:
        memory.record_workflow_event(
            workflow_job_id=request.workflow_job_id,
            stage="public_listening_sync_started",
            status="running",
        )

    for config in configs:
        _report_progress(progress_callback)
        try:
            run = apify_client.run_actor(
                config.actor_id,
                apify_actor_input(config, max_items=max_items_per_source),
            )
            run = apify_client.wait_for_run(
                run,
                progress_callback=(
                    (lambda: _report_progress(progress_callback))
                    if progress_callback is not None
                    else None
                ),
            )
            run_id = str(run.get("id") or "") or None
            dataset_id = run.get("defaultDatasetId") or run.get("default_dataset_id")
            if not dataset_id:
                raise RuntimeError(f"Apify run {run_id or 'unknown'} succeeded without a dataset")
            items = apify_client.fetch_dataset_items(str(dataset_id))
            items = items[:max_items_per_source]
            for item in items:
                _report_progress(progress_callback)
                try:
                    raw = normalize_apify_item(
                        source_type=config.source_type,
                        item=item,
                        actor_id=config.actor_id,
                        run_id=run_id,
                    )
                except ValueError:
                    skipped_count += 1
                    continue
                result = process_signal(
                    SignalProcessingRequest(
                        brand_slug=request.brand_slug,
                        raw_signal=raw,
                        brand_context=request.brand_context,
                        routing_config=request.routing_config,
                        people_config=request.people_config,
                        organization_id=request.tenant.organization_id,
                        brand_id=request.brand_id,
                        model_profile=request.model_profile,
                    ),
                    memory=memory,
                    classifier=classifier,
                    triage_agent=triage_agent,
                )
                if result.status == "duplicate":
                    skipped_count += 1
                elif result.status == "failed":
                    raise RuntimeError(
                        "signal processing failed: "
                        f"{result.error_class or 'unknown'}: {result.error_message or ''}"
                    )
                else:
                    processed_count += 1
                _report_progress(progress_callback)
            memory.record_source_health(
                organization_id=request.tenant.organization_id,
                brand_id=request.brand_id,
                source_type=config.source_type,
                provider="apify",
                status="ok",
                run_id=run_id,
                item_count=len(items),
                checked_at=checked_at,
            )
            synced_sources.append(config.source_type)
        except (LLMGatewayConfigError, LLMGatewayAuthError, PublicListeningProgressError):
            raise
        except Exception as exc:
            failed_sources[config.source_type] = str(exc)
            memory.record_source_health(
                organization_id=request.tenant.organization_id,
                brand_id=request.brand_id,
                source_type=config.source_type,
                provider="apify",
                status="failed",
                error_message=str(exc),
                checked_at=checked_at,
            )

    status = "completed" if not failed_sources else "partial"
    if request.workflow_job_id is not None:
        memory.record_workflow_event(
            workflow_job_id=request.workflow_job_id,
            stage="public_listening_sync_completed",
            status=status,
            event_metadata={
                "processed_count": processed_count,
                "skipped_count": skipped_count,
                "failed_sources": failed_sources,
            },
        )
    return PublicListeningSyncResult(
        status=status,
        synced_sources=synced_sources,
        processed_count=processed_count,
        skipped_count=skipped_count,
        failed_sources=failed_sources,
    )


def _report_progress(callback: Callable[[], None] | None) -> None:
    if callback is None:
        return
    try:
        callback()
    except Exception as exc:
        raise PublicListeningProgressError(f"public listening progress hook failed: {exc}") from exc


@activity.defn
def public_listening_sync_activity(
    request: PublicListeningSyncRequest,
) -> PublicListeningSyncResult:
    return sync_public_listening(request)


@dataclass(frozen=True)
class PublicListeningSourceActivityRequest:
    organization_id: int
    brand_id: int
    brand_slug: str
    workflow_job_id: int
    owner_token: str
    source: ResolvedSourceConfigSnapshot


@dataclass(frozen=True)
class PublicListeningFinalizerRequest:
    organization_id: int
    brand_id: int
    workflow_job_id: int
    owner_token: str
    status: str
    result_summary: dict[str, Any]


NON_RETRYABLE_ACTIVITY_ERRORS = (
    "AdapterBlockedError",
    "LeaseLostError",
    "LLMGatewayAuthError",
    "LLMGatewayConfigError",
    "SourceConfigError",
    "UnresolvedActorStartError",
    "ValueError",
)


@dataclass
class SourceActivityCheckpoint:
    source: str | None = None
    fingerprint: str | None = None
    reservations: dict[str, str] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    datasets: dict[str, dict[str, Any]] = field(default_factory=dict)
    pages: dict[str, int] = field(default_factory=dict)
    completed_paths: list[str] = field(default_factory=list)
    processed_identities: list[str] = field(default_factory=list)
    committed_stages: dict[str, list[str]] = field(default_factory=dict)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    discovery_parents: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reconciled_spend_usd: str = "0"

    @classmethod
    def load(cls) -> SourceActivityCheckpoint:
        try:
            details = activity.info().heartbeat_details
        except RuntimeError:
            return cls()
        if not details or not isinstance(details[-1], Mapping):
            return cls()
        payload = details[-1]
        if payload.get("schema_version") != 1:
            return cls()
        return cls(
            source=str(payload.get("source")) if payload.get("source") else None,
            fingerprint=(str(payload.get("fingerprint")) if payload.get("fingerprint") else None),
            reservations=dict(payload.get("reservations") or {}),
            runs=dict(payload.get("runs") or {}),
            datasets=dict(payload.get("datasets") or {}),
            pages={str(key): int(value) for key, value in (payload.get("pages") or {}).items()},
            completed_paths=list(payload.get("completed_paths") or []),
            processed_identities=list(payload.get("processed_identities") or []),
            committed_stages={
                str(key): list(value)
                for key, value in (payload.get("committed_stages") or {}).items()
            },
            components=dict(payload.get("components") or {}),
            discovery_parents={
                str(key): list(value)
                for key, value in (payload.get("discovery_parents") or {}).items()
            },
            reconciled_spend_usd=str(payload.get("reconciled_spend_usd") or "0"),
        )

    def payload(self, *, source: ResolvedSourceConfigSnapshot, checkpoint: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "source": source.source.value,
            "fingerprint": source.approval_fingerprint.value,
            "checkpoint": checkpoint,
            "reservations": self.reservations,
            "runs": self.runs,
            "datasets": self.datasets,
            "pages": self.pages,
            "completed_paths": self.completed_paths,
            "processed_identities": self.processed_identities[
                -source.limits.max_signals_per_source :
            ],
            "committed_stages": self.committed_stages,
            "components": self.components,
            "discovery_parents": self.discovery_parents,
            "reconciled_spend_usd": self.reconciled_spend_usd,
        }


def _cancellation_requested() -> bool:
    try:
        return activity.is_cancelled()
    except RuntimeError:
        return False


def _heartbeat(
    request: PublicListeningSourceActivityRequest,
    state: SourceActivityCheckpoint,
    checkpoint: str,
) -> None:
    """Heartbeat the complete retry checkpoint and observe executor cancellation."""

    activity.heartbeat(state.payload(source=request.source, checkpoint=checkpoint))
    if _cancellation_requested():
        raise asyncio.CancelledError


def _assert_source_owner(
    request: PublicListeningSourceActivityRequest,
    memory: SqlMemory,
    state: SourceActivityCheckpoint,
    checkpoint: str = "lease_renewal",
) -> None:
    _heartbeat(request, state, checkpoint)
    if not memory.renew_workflow_lease(
        organization_id=request.organization_id,
        brand_id=request.brand_id,
        owner_token=request.owner_token,
        workflow_kind=PUBLIC_LISTENING_WORKFLOW_KIND,
    ):
        raise LeaseLostError("public-listening workflow lease was lost")


def _provider_budget(
    snapshot: ResolvedSourceConfigSnapshot,
    state: SourceActivityCheckpoint,
) -> ProviderBudget:
    evidence = snapshot.provider_evidence
    return ProviderBudget(
        ceiling_usd=snapshot.limits.max_cost_usd_per_source,
        charge_quantum_usd=max(item.charge_quantum_usd for item in evidence),
        minimum_call_charge_usd=max(item.minimum_call_charge_usd for item in evidence),
        conservative_request_cost_usd=max(item.conservative_request_cost_usd for item in evidence),
        reconciled_spend_usd=Decimal(state.reconciled_spend_usd),
    )


def _activity_deadline_monotonic() -> float:
    now_monotonic = time.monotonic()
    try:
        info = activity.info()
    except RuntimeError:
        return now_monotonic + 20 * 60
    timeout = info.start_to_close_timeout or timedelta(minutes=20)
    elapsed = max(0.0, (datetime.now(tz=UTC) - info.started_time).total_seconds())
    return now_monotonic + max(0.0, timeout.total_seconds() - elapsed)


def _typed_selectors(path_config) -> tuple[TypedSelector, ...]:
    return tuple(path_config.selectors)


def _path_plan(
    snapshot: ResolvedSourceConfigSnapshot,
    path_config,
    discovery_parents: dict[SourcePath, list[ParsedProviderSignal]],
) -> AdapterPathPlan:
    adapter = get_source_adapter(snapshot.source.value)
    if hasattr(adapter, "plan_path"):
        discovery_path = (
            SourcePath.OFFICIAL_DISCOVERY
            if path_config.path == SourcePath.OFFICIAL_COMMENTS
            else SourcePath.MENTION_DISCOVERY
            if path_config.path == SourcePath.MENTION_COMMENTS
            else None
        )
        return adapter.plan_path(
            path=path_config.path,
            selectors=_typed_selectors(path_config),
            parents=tuple(discovery_parents.get(discovery_path, ())),
            item_cap=path_config.max_items,
            max_parents=path_config.max_parents,
            max_comments_per_parent=path_config.max_comments_per_parent,
            max_comments=path_config.max_comments,
        )
    plans = _plans_for_path(snapshot, path_config, discovery_parents)
    return AdapterPathPlan(
        path=path_config.path,
        actor_runs=plans,
        empty_reason="no_eligible_parents" if not plans else None,
    )


def _bind_plan_to_snapshot(
    snapshot: ResolvedSourceConfigSnapshot,
    plan: ActorRunPlan,
) -> tuple[ActorRunPlan, Any]:
    actor_role = actor_role_for_path(snapshot.source.value, plan.path)
    evidence = snapshot.evidence_for(plan.path, actor_role)
    actor = ActorRegistration(
        actor_id=evidence.actor_id,
        build_id=evidence.build_id,
        build_number=evidence.build_number,
        minimum_call_charge_usd=evidence.minimum_call_charge_usd,
    )
    return (
        replace(
            plan,
            actor=actor,
            minimum_call_charge_usd=evidence.minimum_call_charge_usd,
        ),
        evidence,
    )


def _plans_for_path(
    snapshot: ResolvedSourceConfigSnapshot,
    path_config,
    discovery_parents: dict[SourcePath, list[ParsedProviderSignal]],
) -> tuple[ActorRunPlan, ...]:
    adapter = get_source_adapter(snapshot.source.value)
    selectors = list(path_config.selectors)
    path = path_config.path
    if snapshot.source.value == "instagram":
        if path == SourcePath.OFFICIAL_DISCOVERY:
            return adapter.plan_official(direct_urls=selectors, item_cap=path_config.max_items)
        if path == SourcePath.MENTION_DISCOVERY:
            from resound.social.apify_adapters.instagram import InstagramMentionSelector

            return adapter.plan_mentions(
                selectors=[InstagramMentionSelector(value) for value in selectors],
                item_cap=path_config.max_items,
            )
        discovery_path = (
            SourcePath.OFFICIAL_DISCOVERY
            if path == SourcePath.OFFICIAL_COMMENTS
            else SourcePath.MENTION_DISCOVERY
        )
        parent_urls = [
            parent.canonical_url
            for parent in discovery_parents.get(discovery_path, [])
            if parent.canonical_url
        ][: path_config.max_parents]
        return adapter.plan_comments(
            path=path,
            parent_urls=parent_urls,
            path_comment_cap=path_config.max_comments,
            max_comments_per_parent=path_config.max_comments_per_parent,
        )
    if snapshot.source.value == "tiktok":
        if path == SourcePath.OFFICIAL_DISCOVERY:
            return adapter.plan_official(
                profiles=selectors,
                item_cap=path_config.max_items,
                comments_per_post=snapshot.limits.max_comments_per_parent,
            )
        if path == SourcePath.MENTION_DISCOVERY:
            return adapter.plan_mentions(
                hashtags=selectors,
                search_queries=[],
                item_cap=path_config.max_items,
                comments_per_post=snapshot.limits.max_comments_per_parent,
            )
        return ()
    if snapshot.source.value == "youtube":
        if path == SourcePath.OFFICIAL_DISCOVERY:
            return adapter.plan_official(channel_urls=selectors, max_items=path_config.max_items)
        return adapter.plan_mentions(search_queries=selectors, max_items=path_config.max_items)
    return adapter.plan(
        path=path,
        **(
            {"subreddits": selectors}
            if snapshot.source.value == "reddit" and path == SourcePath.OFFICIAL_DISCOVERY
            else {"searches": selectors}
            if snapshot.source.value == "reddit"
            else {"twitter_handles": selectors}
            if path == SourcePath.OFFICIAL_DISCOVERY
            else {"search_terms": selectors}
        ),
        max_items=path_config.max_items,
    )


def _parse_provider_item(
    source: str,
    path: SourcePath,
    item: dict[str, Any],
    *,
    parent: ParentContext | None = None,
) -> ParsedProviderSignal:
    adapter = get_source_adapter(source)
    if hasattr(adapter, "parse_path_result"):
        return adapter.parse_path_result(path=path, item=item, parent=parent)
    if source == "instagram":
        if path.value.endswith("comments"):
            return adapter.parse_comment(item)
        return adapter.parse_post(item)
    if source == "tiktok":
        return adapter.parse_video(item)
    return adapter.parse(item)


def _raw_signal(parsed: ParsedProviderSignal, path: SourcePath) -> RawSignal:
    return RawSignal(
        source=parsed.platform,
        provider="apify",
        external_id=parsed.identity.value,
        url=parsed.canonical_url,
        author_handle=parsed.author_handle,
        content=parsed.content,
        posted_at=parsed.provider_timestamp,
        raw_metadata={
            "canonical_platform": parsed.platform,
            "content_kind": parsed.content_kind,
            "path": path.value,
            parsed.identity.kind: parsed.identity.value,
            "parent_url": parsed.parent_url,
            "parent_context": (
                {
                    "platform": parsed.parent_context.platform,
                    "content_kind": parsed.parent_context.content_kind,
                    "author_handle": parsed.parent_context.author_handle,
                    "excerpt": parsed.parent_context.excerpt,
                    "canonical_url": parsed.parent_context.canonical_url,
                    "published_at": (
                        parsed.parent_context.published_at.isoformat()
                        if parsed.parent_context.published_at
                        else None
                    ),
                    "provider_native_id": parsed.parent_context.provider_native_id,
                }
                if parsed.parent_context
                else None
            ),
            "observed_public_metrics": parsed.observed_public_metrics,
        },
    )


def _checkpoint_identity(path: SourcePath, identity_value: str) -> str:
    return f"{path.value}:{identity_value}"


def _serialize_parent(parsed: ParsedProviderSignal) -> dict[str, Any]:
    return {
        "platform": parsed.platform,
        "content_kind": parsed.content_kind,
        "identity": parsed.identity.model_dump(mode="json"),
        "content": parsed.content,
        "provider_timestamp": parsed.provider_timestamp.isoformat(),
        "canonical_url": parsed.canonical_url,
        "author_handle": parsed.author_handle,
        "observed_public_metrics": parsed.observed_public_metrics,
        "comments_dataset_url": parsed.comments_dataset_url,
    }


def _deserialize_parent(payload: Mapping[str, Any]) -> ParsedProviderSignal:
    from resound.social.contracts import CanonicalIdentity

    return ParsedProviderSignal(
        platform=str(payload["platform"]),
        content_kind=str(payload["content_kind"]),
        identity=CanonicalIdentity.model_validate(payload["identity"]),
        content=str(payload["content"]),
        provider_timestamp=datetime.fromisoformat(str(payload["provider_timestamp"])),
        canonical_url=payload.get("canonical_url"),
        author_handle=payload.get("author_handle"),
        observed_public_metrics=dict(payload.get("observed_public_metrics") or {}),
        comments_dataset_url=payload.get("comments_dataset_url"),
    )


def _usage_total(run: Mapping[str, Any]) -> Decimal:
    try:
        usage = Decimal(str(run.get("usageTotalUsd")))
    except (DecimalException, ValueError) as exc:
        raise RuntimeError("terminal Apify Run has missing or malformed usageTotalUsd") from exc
    if not usage.is_finite() or usage < 0:
        raise RuntimeError("terminal Apify Run has missing or malformed usageTotalUsd")
    return usage


def _abort_provider_run(client: Any, run_id: str) -> None:
    abort = getattr(client, "abort_run", None)
    if abort is None:
        return
    try:
        abort(run_id, timeout_seconds=5.0)
    except Exception:
        # Cancellation must not be delayed or replaced by a best-effort cleanup failure.
        pass


def execute_public_listening_source(
    request: PublicListeningSourceActivityRequest,
    *,
    memory: SqlMemory | None = None,
    apify_client: Any | None = None,
) -> AdapterResult:
    """Execute one immutable source snapshot serially on the activity executor."""

    memory = memory or SqlMemory()
    client = apify_client or ApifyClient()
    snapshot = request.source
    state = SourceActivityCheckpoint.load()
    if state.source is not None and state.source != snapshot.source.value:
        raise ValueError("heartbeat checkpoint belongs to a different source")
    if state.fingerprint is not None and state.fingerprint != snapshot.approval_fingerprint.value:
        raise ValueError("heartbeat checkpoint belongs to a different immutable snapshot")
    state.source = snapshot.source.value
    state.fingerprint = snapshot.approval_fingerprint.value
    if state.reservations:
        unresolved = next(
            (reservation for reservation in state.reservations if reservation not in state.runs),
            None,
        )
        if unresolved is not None:
            raise UnresolvedActorStartError(
                unresolved,
                "heartbeat checkpoint contains an actor reservation without an acknowledged Run",
            )
    _assert_source_owner(request, memory, state, "source_entry")
    budget = _provider_budget(snapshot, state)
    deadline = _activity_deadline_monotonic()
    deadline_context = snapshot.limits.deadline_context(
        deadline_monotonic=deadline,
        monotonic=time.monotonic,
    )
    components: list[AdapterComponentResult] = []
    accepted_identities = set(state.processed_identities)
    total_accepted = len(accepted_identities)
    total_comments_accepted = sum(
        value.startswith("official_comments:") or value.startswith("mention_comments:")
        for value in accepted_identities
    )
    discovery_parents: dict[SourcePath, list[ParsedProviderSignal]] = {
        SourcePath(path): [_deserialize_parent(item) for item in items]
        for path, items in state.discovery_parents.items()
    }
    active_run_ids: set[str] = set()
    run_count = len(state.runs)

    for path_config in snapshot.paths:
        path = path_config.path
        if path.value in state.completed_paths:
            payload = state.components.get(path.value)
            if payload is None:
                raise RuntimeError(f"completed path {path.value} is missing its component summary")
            components.append(AdapterComponentResult.model_validate(payload))
            continue
        fetched = processed = resumed = duplicates = skipped = 0
        issues: list[AdapterIssue] = []
        associations: list[SignalAssociation] = []
        runs: list[ProviderRunRef] = []
        datasets: list[ProviderDatasetRef] = []

        def provider_acceptance_cap_reached() -> bool:
            if total_accepted >= snapshot.limits.max_signals_per_source:
                code = "signal_cap_reached"
                message = "source signal cap reached"
            elif (
                path in {SourcePath.OFFICIAL_COMMENTS, SourcePath.MENTION_COMMENTS}
                and total_comments_accepted >= snapshot.limits.max_comments_per_source
            ):
                code = "comment_cap_reached"
                message = "source comment cap reached"
            else:
                return False
            if not any(issue.code == code for issue in issues):
                issues.append(
                    AdapterIssue(
                        path=path,
                        code=code,
                        issue_class="LimitReached",
                        message=message,
                        preserved_work=True,
                    )
                )
            return True

        def consume_items(
            items: list[dict[str, Any]],
            *,
            dataset_id: str,
            parent: ParentContext | None,
        ) -> int:
            nonlocal processed, resumed, duplicates, skipped
            nonlocal total_accepted, total_comments_accepted
            accepted_here = 0
            for item_index, item in enumerate(items):
                if total_accepted >= snapshot.limits.max_signals_per_source:
                    issues.append(
                        AdapterIssue(
                            path=path,
                            code="signal_cap_reached",
                            issue_class="LimitReached",
                            message="source signal cap reached",
                            preserved_work=True,
                        )
                    )
                    skipped += len(items) - item_index
                    break
                if (
                    path in {SourcePath.OFFICIAL_COMMENTS, SourcePath.MENTION_COMMENTS}
                    and total_comments_accepted >= snapshot.limits.max_comments_per_source
                ):
                    issues.append(
                        AdapterIssue(
                            path=path,
                            code="comment_cap_reached",
                            issue_class="LimitReached",
                            message="source comment cap reached",
                            preserved_work=True,
                        )
                    )
                    skipped += len(items) - item_index
                    break
                _heartbeat(request, state, f"parser:{path.value}:{dataset_id}:{item_index}")
                try:
                    parsed = _parse_provider_item(
                        snapshot.source.value,
                        path,
                        item,
                        parent=parent,
                    )
                except ValueError as exc:
                    skipped += 1
                    issues.append(
                        AdapterIssue(
                            path=path,
                            code="parser_rejected",
                            issue_class=type(exc).__name__,
                            message=str(exc),
                            preserved_work=True,
                            dataset_id=dataset_id,
                        )
                    )
                    continue
                if path.value.endswith("discovery"):
                    known = {
                        parent_signal.identity.value
                        for parent_signal in discovery_parents.setdefault(path, [])
                    }
                    if parsed.identity.value not in known:
                        discovery_parents[path].append(parsed)
                        state.discovery_parents[path.value] = [
                            _serialize_parent(parent_signal)
                            for parent_signal in discovery_parents[path]
                        ]
                identity_key = _checkpoint_identity(path, parsed.identity.value)
                if identity_key in accepted_identities:
                    duplicates += 1
                    associations.append(
                        SignalAssociation(
                            path=path,
                            identity=parsed.identity,
                            processing_state="duplicate",
                        )
                    )
                    continue
                _assert_source_owner(
                    request,
                    memory,
                    state,
                    f"before_signal_processing:{identity_key}",
                )

                def processing_heartbeat(stage: str, signal_id: int) -> None:
                    stages = state.committed_stages.setdefault(identity_key, [])
                    if stage not in stages:
                        stages.append(stage)
                    _assert_source_owner(
                        request,
                        memory,
                        state,
                        f"{stage}:{signal_id}",
                    )

                processing = process_signal(
                    SignalProcessingRequest(
                        brand_slug=request.brand_slug,
                        raw_signal=_raw_signal(parsed, path),
                        brand_context=snapshot.processing.brand_context,
                        routing_config=dict(snapshot.processing.routing_config),
                        people_config=dict(snapshot.processing.people_config),
                        organization_id=request.organization_id,
                        brand_id=request.brand_id,
                        workflow_id=str(request.workflow_job_id),
                        model_profile=snapshot.processing.model_profile,
                        owner_token=request.owner_token,
                    ),
                    memory=memory,
                    heartbeat=processing_heartbeat,
                )
                is_resume = signal_processing_is_resume(processing)
                if processing.status == "failed":
                    skipped += 1
                    processing_state = "failed"
                else:
                    accepted_identities.add(identity_key)
                    state.processed_identities.append(identity_key)
                    total_accepted += 1
                    accepted_here += 1
                    if path in {SourcePath.OFFICIAL_COMMENTS, SourcePath.MENTION_COMMENTS}:
                        total_comments_accepted += 1
                    if processing.status == "duplicate":
                        duplicates += 1
                        processing_state = "duplicate"
                    elif is_resume:
                        resumed += max(1, processing.resumed_count)
                        processing_state = "resumed"
                    else:
                        processed += 1
                        processing_state = "processed"
                associations.append(
                    SignalAssociation(
                        path=path,
                        identity=parsed.identity,
                        signal_id=processing.signal_id,
                        processing_state=processing_state,
                    )
                )
                _heartbeat(request, state, f"signal_accounted:{identity_key}")
            return accepted_here

        try:
            path_plan = _path_plan(snapshot, path_config, discovery_parents)
            for index, registry_plan in enumerate(path_plan.actor_runs):
                if provider_acceptance_cap_reached():
                    break
                plan, evidence = _bind_plan_to_snapshot(snapshot, registry_plan)
                reservation_id = f"{path.value}:{index}"
                run_state = state.runs.get(reservation_id)
                if run_state is None:
                    if run_count >= snapshot.limits.max_runs_per_source:
                        raise RuntimeError("source actor Run cap reached")
                    budget.charge_quantum_usd = evidence.charge_quantum_usd
                    budget.minimum_call_charge_usd = evidence.minimum_call_charge_usd
                    budget.conservative_request_cost_usd = evidence.conservative_request_cost_usd
                    charge_cap = budget.remaining_charge_cap()
                    if charge_cap < plan.minimum_call_charge_usd:
                        raise RuntimeError(
                            "remaining provider budget is below the actor call minimum"
                        )

                    def reserve_start() -> Any:
                        reservation = budget.reserve(reservation_id)
                        state.reservations[reservation_id] = format(reservation.amount_usd, "f")
                        _heartbeat(request, state, f"actor_reserved:{reservation_id}")
                        return reservation

                    _assert_source_owner(
                        request,
                        memory,
                        state,
                        f"before_actor_start:{reservation_id}",
                    )
                    run = client.run_actor(
                        plan.actor.actor_id,
                        plan.actor_input,
                        build_number=plan.actor.build_number,
                        expected_build_id=plan.actor.build_id,
                        max_total_charge_usd=charge_cap,
                        reservation_callback=reserve_start,
                        deadline_context=deadline_context,
                        deadline_monotonic=deadline,
                        deadline_reserve_seconds=snapshot.limits.deadline_reserve_seconds,
                        cancellation_requested=_cancellation_requested,
                    )
                    run_id = str(run.get("id") or "").strip()
                    if not run_id:
                        raise UnresolvedActorStartError(
                            reservation_id,
                            "Apify actor start response omitted its acknowledged Run ID",
                        )
                    budget.resolve_start(reservation_id)
                    state.reservations.pop(reservation_id, None)
                    run_state = {
                        "run": dict(run),
                        "charge_cap": format(charge_cap, "f"),
                        "usage_reconciled": False,
                    }
                    state.runs[reservation_id] = run_state
                    run_count += 1
                    _heartbeat(request, state, f"actor_acknowledged:{reservation_id}:{run_id}")
                else:
                    run = dict(run_state["run"])
                    charge_cap = Decimal(str(run_state["charge_cap"]))
                    run_id = str(run.get("id") or "").strip()
                    if not run_id:
                        raise RuntimeError("checkpointed Apify Run is missing its ID")
                active_run_ids.add(run_id)

                def abort_acknowledged_run(cancelled_run_id: str) -> None:
                    _abort_provider_run(client, cancelled_run_id)
                    active_run_ids.discard(cancelled_run_id)

                completed = client.wait_for_run(
                    run,
                    progress_callback=lambda rid=run_id: _assert_source_owner(
                        request, memory, state, f"actor_poll:{rid}"
                    ),
                    deadline_context=deadline_context,
                    deadline_monotonic=deadline,
                    cancellation_requested=_cancellation_requested,
                    cancellation_callback=abort_acknowledged_run,
                )
                active_run_ids.discard(run_id)
                usage = _usage_total(completed)
                if not bool(run_state.get("usage_reconciled")):
                    budget.reconcile(reservation_id, usage)
                    state.reconciled_spend_usd = format(budget.reconciled_spend_usd, "f")
                run_state.update({"run": dict(completed), "usage_reconciled": True})
                _heartbeat(request, state, f"actor_terminal:{reservation_id}:{run_id}")
                dataset_id = str(completed.get("defaultDatasetId") or "")
                if not dataset_id:
                    raise RuntimeError("successful Apify Run is missing defaultDatasetId")
                run_ref = ProviderRunRef(
                    path=path,
                    actor_id=evidence.actor_id,
                    build_id=evidence.build_id,
                    build_number=evidence.build_number,
                    run_id=run_id,
                    requested_row_maximum=plan.requested_row_maximum,
                    max_total_charge_usd=charge_cap,
                    usage_total_usd=usage,
                    status=str(completed.get("status") or "SUCCEEDED"),
                    input_schema_reference=evidence.provider_declared_input_schema_reference,
                    output_schema_reference=evidence.provider_declared_output_schema_reference,
                    fixture_shape_reference=evidence.fixture_derived_shape_reference,
                    dataset_ids=(dataset_id,),
                )
                runs.append(run_ref)
                dataset_key = f"run:{reservation_id}:{dataset_id}"
                dataset_state = state.datasets.get(dataset_key)
                if dataset_state and dataset_state.get("complete"):
                    datasets.append(ProviderDatasetRef.model_validate(dataset_state["reference"]))
                    continue
                if provider_acceptance_cap_reached():
                    continue
                _assert_source_owner(request, memory, state, f"before_dataset:{dataset_key}")
                items = client.fetch_dataset_items(
                    dataset_id,
                    limit=plan.requested_row_maximum,
                    page_size=snapshot.limits.page_size,
                    deadline_context=deadline_context,
                    deadline_monotonic=deadline,
                    cancellation_requested=_cancellation_requested,
                )
                fetched += len(items)
                before = processed + resumed + duplicates
                consume_items(list(items), dataset_id=dataset_id, parent=None)
                raw_count = int(getattr(items, "raw_count", len(items)))
                over_return_count = max(0, raw_count - plan.requested_row_maximum)
                over_return = getattr(items, "over_return", None)
                if over_return is not None:
                    issues.append(over_return.as_issue(path=path, dataset_id=dataset_id))
                dataset_ref = ProviderDatasetRef(
                    path=path,
                    dataset_id=dataset_id,
                    run_id=run_id,
                    requested_limit=plan.requested_row_maximum,
                    fetched_count=len(items),
                    processed_count=processed + resumed + duplicates - before,
                    raw_fetched_count=raw_count,
                    provider_over_return_count=over_return_count,
                )
                datasets.append(dataset_ref)
                state.datasets[dataset_key] = {
                    "complete": True,
                    "reference": dataset_ref.model_dump(mode="json"),
                }
                state.pages[dataset_key] = len(items)
                _heartbeat(request, state, f"dataset_complete:{dataset_key}")

            for index, dataset_plan in enumerate(path_plan.dataset_fetches):
                if provider_acceptance_cap_reached():
                    break
                evidence = snapshot.evidence_for(
                    path,
                    actor_role_for_path(snapshot.source.value, path),
                )
                dataset_key = f"secondary:{path.value}:{index}:{dataset_plan.dataset_id}"
                dataset_state = state.datasets.get(dataset_key)
                if dataset_state and dataset_state.get("complete"):
                    datasets.append(ProviderDatasetRef.model_validate(dataset_state["reference"]))
                    continue
                _assert_source_owner(request, memory, state, f"before_dataset:{dataset_key}")
                items = client.fetch_dataset_items(
                    dataset_plan.dataset_id,
                    dataset_url=dataset_plan.dataset_url,
                    limit=dataset_plan.requested_limit,
                    page_size=snapshot.limits.page_size,
                    deadline_context=deadline_context,
                    deadline_monotonic=deadline,
                    cancellation_requested=_cancellation_requested,
                )
                fetched += len(items)
                before = processed + resumed + duplicates
                consume_items(
                    list(items),
                    dataset_id=dataset_plan.dataset_id,
                    parent=dataset_plan.parent,
                )
                raw_count = int(getattr(items, "raw_count", len(items)))
                over_return_count = max(0, raw_count - dataset_plan.requested_limit)
                over_return = getattr(items, "over_return", None)
                if over_return is not None:
                    issues.append(
                        over_return.as_issue(path=path, dataset_id=dataset_plan.dataset_id)
                    )
                provenance = {
                    **dataset_plan.provenance,
                    "dataset_url": dataset_plan.dataset_url,
                    "actor_role": evidence.actor_role.value,
                    "input_schema_reference": evidence.provider_declared_input_schema_reference,
                    "output_schema_reference": evidence.provider_declared_output_schema_reference,
                    "fixture_shape_reference": evidence.fixture_derived_shape_reference,
                }
                dataset_ref = ProviderDatasetRef(
                    path=path,
                    dataset_id=dataset_plan.dataset_id,
                    parent_identity_value=dataset_plan.provenance.get("parent_identity"),
                    requested_limit=dataset_plan.requested_limit,
                    fetched_count=len(items),
                    processed_count=processed + resumed + duplicates - before,
                    raw_fetched_count=raw_count,
                    provider_over_return_count=over_return_count,
                    provenance=provenance,
                )
                datasets.append(dataset_ref)
                state.datasets[dataset_key] = {
                    "complete": True,
                    "reference": dataset_ref.model_dump(mode="json"),
                }
                state.pages[dataset_key] = len(items)
                _heartbeat(request, state, f"dataset_complete:{dataset_key}")
            component_status = "partial" if issues else "ok"
        except (
            AdapterBlockedError,
            LeaseLostError,
            LLMGatewayAuthError,
            LLMGatewayConfigError,
            SourceConfigError,
            UnresolvedActorStartError,
            ValueError,
            asyncio.CancelledError,
        ):
            for run_id in active_run_ids:
                _abort_provider_run(client, run_id)
            raise
        except Exception as exc:
            if _cancellation_requested():
                for run_id in active_run_ids:
                    _abort_provider_run(client, run_id)
                raise asyncio.CancelledError from exc
            component_status = "partial" if processed or duplicates else "failed"
            issues.append(
                AdapterIssue(
                    path=path,
                    code="path_execution_failed",
                    issue_class=type(exc).__name__,
                    message=str(exc),
                    retryable=True,
                    preserved_work=bool(processed or duplicates),
                )
            )
        component = AdapterComponentResult(
            path=path,
            status=component_status,
            fetched_count=fetched,
            processed_count=processed,
            resumed_count=resumed,
            duplicate_count=duplicates,
            skipped_count=skipped,
            cost_usd=sum((run.usage_total_usd or Decimal("0") for run in runs), Decimal("0")),
            runs=tuple(runs),
            datasets=tuple(datasets),
            issues=tuple(issues),
            associations=tuple(associations),
        )
        _assert_source_owner(request, memory, state, f"before_health:{path.value}")
        memory.record_source_health(
            organization_id=request.organization_id,
            brand_id=request.brand_id,
            source_type=snapshot.source.value,
            canonical_source=snapshot.storage_platform,
            provider="apify",
            path=path.value,
            status=component.status,
            fetched_count=component.fetched_count,
            processed_count=component.processed_count,
            duplicate_count=component.duplicate_count,
            cost_usd=component.cost_usd,
            provenance={
                "fingerprint": snapshot.approval_fingerprint.value,
                "runs": [run.model_dump(mode="json") for run in component.runs],
                "datasets": [dataset.model_dump(mode="json") for dataset in component.datasets],
            },
            issues=[issue.model_dump(mode="json") for issue in component.issues],
        )
        state.components[path.value] = component.model_dump(mode="json")
        if path.value not in state.completed_paths:
            state.completed_paths.append(path.value)
        _heartbeat(request, state, f"path_complete:{path.value}")
        components.append(component)

    rank = {"ok": 0, "partial": 1, "failed": 2}
    source_status = max((component.status for component in components), key=rank.get, default="ok")
    return AdapterResult(
        source=snapshot.source,
        platform=snapshot.storage_platform,
        status=source_status,
        paths=tuple(components),
        max_signals_per_source=snapshot.limits.max_signals_per_source,
        fetched_count=sum(item.fetched_count for item in components),
        processed_count=sum(item.processed_count for item in components),
        resumed_count=sum(item.resumed_count for item in components),
        duplicate_count=sum(item.duplicate_count for item in components),
        skipped_count=sum(item.skipped_count for item in components),
        cost_usd=sum((item.cost_usd for item in components), Decimal("0")),
        cap_reached=(
            total_accepted >= snapshot.limits.max_signals_per_source
            or total_comments_accepted >= snapshot.limits.max_comments_per_source
        ),
        config_fingerprint=snapshot.approval_fingerprint,
    )


@activity.defn
def public_listening_source_activity(
    request: PublicListeningSourceActivityRequest,
) -> AdapterResult:
    return execute_public_listening_source(request)


@activity.defn
def public_listening_finalizer_activity(request: PublicListeningFinalizerRequest) -> bool:
    activity.heartbeat({"checkpoint": "atomic_finalization", "status": request.status})
    finalized = SqlMemory().finalize_workflow_job(
        workflow_job_id=request.workflow_job_id,
        organization_id=request.organization_id,
        brand_id=request.brand_id,
        owner_token=request.owner_token,
        status=request.status,
        result_summary=request.result_summary,
    )
    if not finalized:
        raise LeaseLostError("workflow finalization lost lease ownership")
    return True


def _aggregate_resolved_results(
    request: ResolvedPublicListeningRequest,
    sources: list[AdapterResult],
) -> ResolvedPublicListeningSyncResult:
    statuses = {item.status for item in sources}
    usable = sum(
        item.processed_count + item.resumed_count + item.duplicate_count for item in sources
    )
    status = "completed" if statuses <= {"ok"} else "failed" if not usable else "partial"
    return ResolvedPublicListeningSyncResult(
        status=status,
        selected_sources=tuple(snapshot.source for snapshot in request.sources),
        selected_paths=request.selected_paths,
        sources=tuple(sources),
        effective_signal_caps={
            snapshot.source.value: snapshot.limits.max_signals_per_source
            for snapshot in request.sources
        },
        fetched_count=sum(item.fetched_count for item in sources),
        processed_count=sum(item.processed_count for item in sources),
        resumed_count=sum(item.resumed_count for item in sources),
        duplicate_count=sum(item.duplicate_count for item in sources),
        skipped_count=sum(item.skipped_count for item in sources),
        cost_usd=sum((item.cost_usd for item in sources), Decimal("0")),
        fingerprints=request.fingerprints,
        lease_outcome="released",
    )


async def _finalize_resolved(
    request: ResolvedPublicListeningRequest,
    status: str,
    summary: dict[str, Any],
) -> None:
    assert request.organization_id is not None
    assert request.workflow_job_id is not None
    assert request.owner_token is not None
    handle = workflow.start_activity(
        public_listening_finalizer_activity,
        PublicListeningFinalizerRequest(
            request.organization_id,
            request.brand_id,
            request.workflow_job_id,
            request.owner_token,
            status,
            summary,
        ),
        start_to_close_timeout=timedelta(minutes=2),
        heartbeat_timeout=timedelta(seconds=30),
        cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
    )
    await asyncio.shield(handle)


@workflow.defn
class PublicListeningSyncWorkflow:
    @workflow.run
    async def run(self, request: PublicListeningSyncRequest | ResolvedPublicListeningRequest):
        if isinstance(request, ResolvedPublicListeningRequest):
            if (
                request.organization_id is None
                or request.workflow_job_id is None
                or not request.owner_token
            ):
                raise ValueError(
                    "resolved public-listening workflow requires organization, job, and owner"
                )
            from temporalio.common import RetryPolicy

            handles = [
                workflow.start_activity(
                    public_listening_source_activity,
                    PublicListeningSourceActivityRequest(
                        request.organization_id,
                        request.brand_id,
                        request.brand_slug,
                        request.workflow_job_id,
                        request.owner_token,
                        snapshot,
                    ),
                    schedule_to_close_timeout=timedelta(minutes=28),
                    start_to_close_timeout=timedelta(minutes=20),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        backoff_coefficient=2,
                        maximum_interval=timedelta(seconds=60),
                        maximum_attempts=2,
                        non_retryable_error_types=NON_RETRYABLE_ACTIVITY_ERRORS,
                    ),
                    cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                    activity_id=f"source:{snapshot.source.value}",
                )
                for snapshot in request.sources
            ]
            try:
                # Shield the group so workflow cancellation cannot implicitly cancel children
                # before we issue and await the explicit ordered cancellation below.
                results = list(await asyncio.shield(asyncio.gather(*handles)))
            except BaseException as exc:
                unfinished = [handle for handle in handles if not handle.done()]
                for handle in unfinished:
                    handle.cancel()
                if unfinished:
                    await asyncio.gather(*unfinished, return_exceptions=True)
                completed_sources = []
                for handle in handles:
                    if not handle.done() or handle.cancelled():
                        continue
                    try:
                        completed_sources.append(handle.result())
                    except BaseException:
                        pass
                terminal_status = (
                    "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
                )
                summary = {
                    "schema_version": "1",
                    "status": terminal_status,
                    "sources": [source.model_dump(mode="json") for source in completed_sources],
                }
                await _finalize_resolved(request, terminal_status, summary)
                raise
            result = _aggregate_resolved_results(request, results)
            await _finalize_resolved(request, result.status, result.model_dump(mode="json"))
            return result
        return await workflow.execute_activity(
            public_listening_sync_activity,
            request,
            start_to_close_timeout=timedelta(minutes=15),
        )
