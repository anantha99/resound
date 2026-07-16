"""Public listening sync workflow backed by Apify."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from resound.agents.signal_triage import SignalTriageAgent
from resound.core.classifier import Classifier
from resound.gateway import LLMGatewayAuthError, LLMGatewayConfigError
from resound.memory import SqlMemory
from resound.social import (
    ListeningProfile,
    SourceType,
    build_apify_query_configs,
    normalize_apify_item,
)
from resound.social.apify import ApifyClient, apify_actor_input
from resound.tenancy import TenantContext
from resound.workflows.signal_processing import SignalProcessingRequest, process_signal
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
        raise PublicListeningProgressError(
            f"public listening progress hook failed: {exc}"
        ) from exc


@activity.defn
async def public_listening_sync_activity(
    request: PublicListeningSyncRequest,
) -> PublicListeningSyncResult:
    return sync_public_listening(request)


@workflow.defn
class PublicListeningSyncWorkflow:
    @workflow.run
    async def run(self, request: PublicListeningSyncRequest) -> PublicListeningSyncResult:
        return await workflow.execute_activity(
            public_listening_sync_activity,
            request,
            start_to_close_timeout=timedelta(minutes=15),
        )
