"""Public listening sync workflow backed by Apify."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
    ParsedProviderSignal,
)
from resound.social.common import ProviderBudget
from resound.social.config import SourceConfigError
from resound.tenancy import TenantContext
from resound.workflows.leases import PUBLIC_LISTENING_WORKFLOW_KIND
from resound.workflows.signal_processing import (
    LeaseLostError,
    SignalProcessingRequest,
    process_signal,
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
    "ValueError",
)


def _heartbeat(details: dict[str, Any]) -> None:
    """Heartbeat and observe cancellation from a synchronous executor activity."""

    activity.heartbeat(details)
    if activity.is_cancelled():
        raise asyncio.CancelledError


def _assert_source_owner(request: PublicListeningSourceActivityRequest, memory: SqlMemory) -> None:
    _heartbeat(
        {
            "source": request.source.source.value,
            "fingerprint": request.source.approval_fingerprint.value,
            "checkpoint": "lease_renewal",
        }
    )
    if not memory.renew_workflow_lease(
        organization_id=request.organization_id,
        brand_id=request.brand_id,
        owner_token=request.owner_token,
        workflow_kind=PUBLIC_LISTENING_WORKFLOW_KIND,
    ):
        raise LeaseLostError("public-listening workflow lease was lost")


def _provider_budget(snapshot: ResolvedSourceConfigSnapshot) -> ProviderBudget:
    evidence = snapshot.provider_evidence[0]
    return ProviderBudget(
        ceiling_usd=snapshot.limits.max_cost_usd_per_source,
        charge_quantum_usd=evidence.charge_quantum_usd,
        minimum_call_charge_usd=evidence.minimum_call_charge_usd,
        conservative_request_cost_usd=evidence.conservative_request_cost_usd,
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
    source: str, path: SourcePath, item: dict[str, Any]
) -> ParsedProviderSignal:
    adapter = get_source_adapter(source)
    if source == "instagram":
        if path.value.endswith("comments"):
            return adapter.parse_comment(item)
        return adapter.parse_post(item)
    if source == "tiktok":
        return adapter.parse_video(item)
    return adapter.parse(item)


def _raw_signal(parsed: ParsedProviderSignal) -> RawSignal:
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
            parsed.identity.kind: parsed.identity.value,
            "parent_url": parsed.parent_url,
        },
    )


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
    _assert_source_owner(request, memory)
    budget = _provider_budget(snapshot)
    components: list[AdapterComponentResult] = []
    total_accepted = 0
    discovery_parents: dict[SourcePath, list[ParsedProviderSignal]] = {}

    for path_config in snapshot.paths:
        path = path_config.path
        fetched = processed = resumed = duplicates = skipped = 0
        issues: list[AdapterIssue] = []
        associations: list[SignalAssociation] = []
        runs = []
        datasets = []
        try:
            plans = _plans_for_path(snapshot, path_config, discovery_parents)
            for index, plan in enumerate(plans):
                _assert_source_owner(request, memory)
                reservation_id = f"{path.value}:{index}"
                charge_cap = budget.remaining_charge_cap()
                _heartbeat(
                    {
                        "source": snapshot.source.value,
                        "path": path.value,
                        "checkpoint": "before_actor_start",
                        "reservation": reservation_id,
                    }
                )
                run = client.run_actor(
                    plan.actor.actor_id,
                    plan.actor_input,
                    build_number=plan.actor.build_number,
                    expected_build_id=plan.actor.build_id,
                    max_total_charge_usd=charge_cap,
                    reservation_callback=lambda rid=reservation_id: budget.reserve(rid),
                    cancellation_requested=activity.is_cancelled,
                )
                _heartbeat(
                    {
                        "source": snapshot.source.value,
                        "path": path.value,
                        "checkpoint": "after_actor_start",
                        "run_id": run.get("id"),
                    }
                )
                completed = client.wait_for_run(
                    run,
                    progress_callback=lambda: _heartbeat(
                        {
                            "source": snapshot.source.value,
                            "path": path.value,
                            "checkpoint": "actor_poll",
                            "run_id": run.get("id"),
                        }
                    ),
                    cancellation_requested=activity.is_cancelled,
                )
                usage = Decimal(str(completed.get("usageTotalUsd")))
                budget.reconcile(reservation_id, usage)
                dataset_id = str(completed.get("defaultDatasetId") or "")
                if not dataset_id:
                    raise RuntimeError("successful Apify Run is missing defaultDatasetId")
                items = client.fetch_dataset_items(
                    dataset_id,
                    limit=plan.requested_row_maximum,
                    page_size=snapshot.limits.page_size,
                    cancellation_requested=activity.is_cancelled,
                )
                fetched += len(items)
                from resound.social import ProviderDatasetRef, ProviderRunRef

                runs.append(
                    ProviderRunRef(
                        path=path,
                        actor_id=plan.actor.actor_id,
                        build_id=plan.actor.build_id,
                        build_number=plan.actor.build_number,
                        run_id=str(completed.get("id") or "") or None,
                        requested_row_maximum=plan.requested_row_maximum,
                        max_total_charge_usd=charge_cap,
                        usage_total_usd=usage,
                        status=str(completed.get("status") or "SUCCEEDED"),
                        input_schema_reference=snapshot.provider_evidence[
                            0
                        ].provider_declared_input_schema_reference,
                        output_schema_reference=snapshot.provider_evidence[
                            0
                        ].provider_declared_output_schema_reference,
                        fixture_shape_reference=snapshot.provider_evidence[
                            0
                        ].fixture_derived_shape_reference,
                        dataset_ids=(dataset_id,),
                    )
                )
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
                    _heartbeat(
                        {
                            "source": snapshot.source.value,
                            "path": path.value,
                            "checkpoint": "parser_batch",
                            "dataset_id": dataset_id,
                            "item": item_index,
                        }
                    )
                    try:
                        parsed = _parse_provider_item(snapshot.source.value, path, item)
                    except ValueError as exc:
                        skipped += 1
                        issues.append(
                            AdapterIssue(
                                path=path,
                                code="parser_rejected",
                                issue_class=type(exc).__name__,
                                message=str(exc),
                                preserved_work=True,
                            )
                        )
                        continue
                    if path.value.endswith("discovery"):
                        discovery_parents.setdefault(path, []).append(parsed)
                    _assert_source_owner(request, memory)
                    processing = process_signal(
                        SignalProcessingRequest(
                            brand_slug=request.brand_slug,
                            raw_signal=_raw_signal(parsed),
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
                        heartbeat=lambda stage, signal_id: _heartbeat(
                            {
                                "source": snapshot.source.value,
                                "path": path.value,
                                "checkpoint": stage,
                                "signal_id": signal_id,
                            }
                        ),
                    )
                    total_accepted += 1
                    if processing.status == "duplicate":
                        duplicates += 1
                    elif processing.status == "failed":
                        skipped += 1
                    else:
                        processed += 1
                    associations.append(
                        SignalAssociation(
                            path=path,
                            identity=parsed.identity,
                            signal_id=processing.signal_id,
                            processing_state="duplicate"
                            if processing.status == "duplicate"
                            else "failed"
                            if processing.status == "failed"
                            else "processed",
                        )
                    )
                datasets.append(
                    ProviderDatasetRef(
                        path=path,
                        dataset_id=dataset_id,
                        run_id=str(completed.get("id") or "") or None,
                        requested_limit=plan.requested_row_maximum,
                        fetched_count=len(items),
                        processed_count=processed,
                    )
                )
            component_status = "partial" if issues else "ok"
        except (
            AdapterBlockedError,
            LeaseLostError,
            LLMGatewayAuthError,
            LLMGatewayConfigError,
            SourceConfigError,
            ValueError,
            asyncio.CancelledError,
        ):
            raise
        except Exception as exc:
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
        _assert_source_owner(request, memory)
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
        _heartbeat(
            {"source": snapshot.source.value, "path": path.value, "checkpoint": "health_write"}
        )
        components.append(component)

    rank = {"ok": 0, "partial": 1, "failed": 2}
    source_status = max((component.status for component in components), key=rank.get)
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
        cap_reached=total_accepted >= snapshot.limits.max_signals_per_source,
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
