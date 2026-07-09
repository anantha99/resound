"""Guided listening profile setup workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from resound.memory import SqlMemory
from resound.social import V1_PUBLIC_SOURCE_TYPES, ListeningProfile
from resound.tenancy import TenantContext
from resound.workflows.temporal_compat import activity, workflow


@dataclass(frozen=True)
class ListeningProfileSetupRequest:
    tenant: TenantContext
    brand_id: int
    brand_slug: str
    brand_names: list[str]
    product_names: list[str]
    competitor_names: list[str] | None = None
    excluded_terms: list[str] | None = None
    locale: str | None = None
    language: str = "en"
    setup_notes: str | None = None
    workflow_job_id: int | None = None


@dataclass(frozen=True)
class ListeningProfileSetupResult:
    profile_id: int
    suggestion_count: int
    status: str


def setup_listening_profile(
    request: ListeningProfileSetupRequest,
    *,
    memory: SqlMemory | None = None,
) -> ListeningProfileSetupResult:
    memory = memory or SqlMemory()
    if request.workflow_job_id is not None:
        memory.record_workflow_event(
            workflow_job_id=request.workflow_job_id,
            stage="listening_profile_setup_started",
            status="running",
        )

    profile_id = memory.save_listening_profile(
        organization_id=request.tenant.organization_id,
        brand_id=request.brand_id,
        authored_by="agent",
        profile=ListeningProfile(
            brand_slug=request.brand_slug,
            brand_names=_clean_terms(request.brand_names) or [request.brand_slug],
            product_names=_clean_terms(request.product_names),
            competitor_names=_clean_terms(request.competitor_names or []),
            excluded_terms=_clean_terms(request.excluded_terms or []),
            enabled_sources=[],
            locale=request.locale,
            language=request.language,
            setup_notes=request.setup_notes,
            confidence=0.65,
        ),
    )
    suggestion_count = _create_setup_suggestions(memory, profile_id, request)

    if request.workflow_job_id is not None:
        memory.record_workflow_event(
            workflow_job_id=request.workflow_job_id,
            stage="listening_profile_setup_completed",
            status="waiting_for_approval",
            event_metadata={"profile_id": profile_id, "suggestion_count": suggestion_count},
        )
    return ListeningProfileSetupResult(
        profile_id=profile_id,
        suggestion_count=suggestion_count,
        status="waiting_for_approval",
    )


def _create_setup_suggestions(
    memory: SqlMemory,
    profile_id: int,
    request: ListeningProfileSetupRequest,
) -> int:
    count = 0
    for term in _suggested_keywords(request):
        memory.create_listening_profile_suggestion(
            profile_id=profile_id,
            suggestion_type="keyword",
            value=term,
            reason="Seeded from the brand setup inputs.",
        )
        count += 1
    for source_type in sorted(V1_PUBLIC_SOURCE_TYPES):
        memory.create_listening_profile_suggestion(
            profile_id=profile_id,
            suggestion_type="source",
            value=source_type,
            reason="Supported public-listening source for initial coverage.",
        )
        count += 1
    return count


def _suggested_keywords(request: ListeningProfileSetupRequest) -> list[str]:
    terms = [
        *_clean_terms(request.brand_names),
        *_clean_terms(request.product_names),
        *_clean_terms(request.competitor_names or []),
    ]
    return sorted(dict.fromkeys(terms))


def _clean_terms(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


@activity.defn
async def listening_profile_setup_activity(
    request: ListeningProfileSetupRequest,
) -> ListeningProfileSetupResult:
    return setup_listening_profile(request)


@workflow.defn
class ListeningProfileSetupWorkflow:
    @workflow.run
    async def run(self, request: ListeningProfileSetupRequest) -> ListeningProfileSetupResult:
        return await workflow.execute_activity(
            listening_profile_setup_activity,
            request,
            start_to_close_timeout=timedelta(minutes=5),
        )
