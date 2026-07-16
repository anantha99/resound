"""Safe, repeatable population of the two approved demo brands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from resound.config import BrandConfig, load_brand_config
from resound.gateway import (
    DEMO_POPULATION_MODEL_PROFILE,
    DEMO_POPULATION_RELIABLE_MODEL_PROFILE,
)
from resound.memory import (
    ClassificationRow,
    LLMCallRow,
    RouteRow,
    SignalRow,
    SourceHealthRow,
    SqlMemory,
    WorkflowJobRow,
)
from resound.social import V1_PUBLIC_SOURCE_TYPES, ListeningProfile, SourceType
from resound.tenancy import TenantContext
from resound.workflows.public_listening import (
    PublicListeningSyncRequest,
    PublicListeningSyncResult,
    sync_public_listening,
)

DEMO_BRANDS = ("liquiddeath", "notion")
DEFAULT_MAX_ITEMS = 10
MAX_ITEMS_LIMIT = 100
LOCK_WORKFLOW_TYPE = "demo_population"
LOCK_LEASE_DURATION = timedelta(minutes=30)


class DemoPopulationAlreadyRunningError(RuntimeError):
    """Raised when an organization already has a population run in progress."""


@dataclass(frozen=True)
class SeededDemoBrand:
    slug: str
    organization_id: int
    brand_id: int


@dataclass(frozen=True)
class PopulationLease:
    job_id: int
    owner_token: str


@dataclass(frozen=True)
class DemoBrandPopulationSummary:
    brand: str
    sources: list[str]
    processed: int = 0
    skipped: int = 0
    health: dict[str, str] = field(default_factory=dict)
    total_volume: int = 0
    relevant_count: int = 0
    route_count: int = 0
    llm_cost_usd: float = 0.0
    llm_latency_ms: dict[str, dict[str, float]] = field(default_factory=dict)
    failure_reason: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure_reason is None


@dataclass(frozen=True)
class DemoPopulationSummary:
    organization: str
    mode: str
    brands: list[DemoBrandPopulationSummary]

    @property
    def succeeded(self) -> bool:
        return all(brand.succeeded for brand in self.brands)


SyncFunction = Callable[..., PublicListeningSyncResult]


def validate_demo_brands(
    brands: list[str] | None,
    brands_dir: Path = Path("brands"),
) -> list[str]:
    requested = brands or list(DEMO_BRANDS)
    invalid = sorted(set(requested) - set(DEMO_BRANDS))
    if invalid:
        raise ValueError(
            f"Unsupported demo brand(s): {', '.join(invalid)}. "
            f"Choose from: {', '.join(DEMO_BRANDS)}"
        )
    missing = [slug for slug in requested if not (brands_dir / slug / "brand.yaml").is_file()]
    if missing:
        raise FileNotFoundError(f"Missing demo brand bundle(s): {', '.join(missing)}")
    return _unique(requested)


def seed_demo_brands(
    memory: SqlMemory,
    *,
    organization: str = "demo",
    brands: list[str] | None = None,
    brands_dir: Path = Path("brands"),
) -> list[SeededDemoBrand]:
    """Idempotently ensure tenant rows and listening profiles for demo brands."""
    slugs = validate_demo_brands(brands, brands_dir)
    organization_id = memory.ensure_organization(organization, organization.title())
    seeded: list[SeededDemoBrand] = []
    for slug in slugs:
        cfg = load_brand_config(slug, brands_dir=brands_dir)
        enabled_sources = _enabled_public_sources(cfg)
        brand = memory.ensure_brand(
            organization_id,
            cfg.slug,
            cfg.name,
            description=cfg.description,
            source_config=cfg.sources,
        )
        memory.save_listening_profile(
            organization_id=organization_id,
            brand_id=brand.id,
            profile=build_brand_listening_profile(cfg, enabled_sources),
            authored_by="agent",
        )
        seeded.append(
            SeededDemoBrand(
                slug=slug,
                organization_id=organization_id,
                brand_id=brand.id,
            )
        )
    return seeded


def populate_demo_brands(
    *,
    organization: str = "demo",
    brands: list[str] | None = None,
    sources: list[SourceType] | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
    dry_run: bool = False,
    seed_only: bool = False,
    continue_on_error: bool = False,
    reliable_classifier: bool = False,
    brands_dir: Path = Path("brands"),
    memory: SqlMemory | None = None,
    sync_fn: SyncFunction = sync_public_listening,
) -> DemoPopulationSummary:
    """Seed and optionally populate the approved brands with bounded ingestion."""
    if dry_run and seed_only:
        raise ValueError("--dry-run and --seed-only cannot be used together")
    if not 1 <= max_items <= MAX_ITEMS_LIMIT:
        raise ValueError(f"max_items must be between 1 and {MAX_ITEMS_LIMIT}")
    slugs = validate_demo_brands(brands, brands_dir)
    selected_sources = sources or ["reddit"]
    model_profile = (
        DEMO_POPULATION_RELIABLE_MODEL_PROFILE
        if reliable_classifier
        else DEMO_POPULATION_MODEL_PROFILE
    )
    invalid_sources = sorted(set(selected_sources) - V1_PUBLIC_SOURCE_TYPES)
    if invalid_sources:
        raise ValueError(f"Unsupported public source(s): {', '.join(invalid_sources)}")

    if dry_run:
        return DemoPopulationSummary(
            organization=organization,
            mode="dry-run",
            brands=[
                DemoBrandPopulationSummary(
                    brand=slug,
                    sources=list(selected_sources),
                )
                for slug in slugs
            ],
        )

    memory = memory or SqlMemory()
    if seed_only:
        seeded = seed_demo_brands(
            memory,
            organization=organization,
            brands=slugs,
            brands_dir=brands_dir,
        )
        return DemoPopulationSummary(
            organization=organization,
            mode="seed-only",
            brands=[
                DemoBrandPopulationSummary(
                    brand=item.slug,
                    sources=list(selected_sources),
                )
                for item in seeded
            ],
        )

    organization_id = memory.ensure_organization(organization, organization.title())
    lease = _acquire_population_lock(memory, organization_id)
    summaries: list[DemoBrandPopulationSummary] = []
    final_status = "completed"
    try:
        seeded = seed_demo_brands(
            memory,
            organization=organization,
            brands=slugs,
            brands_dir=brands_dir,
        )
        for item in seeded:
            _renew_population_lock(memory, lease)
            cfg = load_brand_config(item.slug, brands_dir=brands_dir)
            started_at = _utc_now()
            try:
                result = sync_fn(
                    PublicListeningSyncRequest(
                        tenant=TenantContext(
                            item.organization_id,
                            organization,
                            team_id=None,
                            user_id=None,
                        ),
                        brand_id=item.brand_id,
                        brand_slug=item.slug,
                        brand_context=cfg.understanding,
                        routing_config=cfg.routing,
                        people_config=cfg.people,
                        enabled_sources=selected_sources,
                        max_items_per_source=max_items,
                        model_profile=model_profile,
                    ),
                    memory=memory,
                    progress_callback=lambda: _renew_population_lock(memory, lease),
                )
                summary = _population_result(memory, item, selected_sources, result, started_at)
            except Exception as exc:
                summary = DemoBrandPopulationSummary(
                    brand=item.slug,
                    sources=list(selected_sources),
                    failure_reason=str(exc) or exc.__class__.__name__,
                )
            summaries.append(summary)
            if not summary.succeeded:
                final_status = "failed"
                if not continue_on_error:
                    break
    except BaseException:
        final_status = "failed"
        raise
    finally:
        if not _release_population_lock(memory, lease, final_status):
            raise DemoPopulationAlreadyRunningError(
                "Demo population lease ownership was lost before release"
            )

    return DemoPopulationSummary(organization=organization, mode="populate", brands=summaries)


def build_brand_listening_profile(
    cfg: BrandConfig,
    enabled_sources: list[SourceType],
) -> ListeningProfile:
    language = "en"
    for settings in cfg.sources.values():
        if isinstance(settings, dict) and isinstance(settings.get("language"), str):
            language = settings["language"]
            break
    return ListeningProfile(
        brand_slug=cfg.slug,
        brand_names=_unique([cfg.name, cfg.slug]),
        keywords=brand_search_terms(cfg),
        enabled_sources=enabled_sources,
        language=language,
        source_config={
            source: dict(settings)
            for source, settings in cfg.sources.items()
            if source in V1_PUBLIC_SOURCE_TYPES and isinstance(settings, dict)
        },
    )


def _enabled_public_sources(cfg: BrandConfig) -> list[SourceType]:
    return [
        source
        for source in sorted(V1_PUBLIC_SOURCE_TYPES)
        if isinstance(cfg.sources.get(source), dict) and cfg.sources[source].get("enabled", True)
    ]


def brand_search_terms(cfg: BrandConfig) -> list[str]:
    terms: list[str] = []
    for settings in cfg.sources.values():
        if not isinstance(settings, dict):
            continue
        for key in ("search_terms", "keywords"):
            terms.extend(_string_values(settings.get(key)))
    return _unique(terms)


def _population_result(
    memory: SqlMemory,
    seeded: SeededDemoBrand,
    sources: list[SourceType],
    result: PublicListeningSyncResult,
    started_at: datetime,
) -> DemoBrandPopulationSummary:
    with memory.session() as session:
        tenant_brand = (
            SignalRow.organization_id == seeded.organization_id,
            SignalRow.brand_id == seeded.brand_id,
        )
        total_volume = session.scalar(
            select(func.count(SignalRow.id))
            .join(ClassificationRow, ClassificationRow.signal_id == SignalRow.id)
            .join(RouteRow, RouteRow.signal_id == SignalRow.id)
            .where(
                *tenant_brand,
                ClassificationRow.classified_at >= started_at,
            )
        ) or 0
        route_count = session.scalar(
            select(func.count(RouteRow.id))
            .join(SignalRow)
            .where(
                *tenant_brand,
                RouteRow.routed_at >= started_at,
            )
        ) or 0
        relevant_count = session.scalar(
            select(func.count(ClassificationRow.id))
            .join(SignalRow)
            .where(
                *tenant_brand,
                ClassificationRow.classified_at >= started_at,
                ClassificationRow.is_about_brand.is_(True),
            )
        ) or 0
        health_rows = list(
            session.execute(
                select(SourceHealthRow).where(
                    SourceHealthRow.organization_id == seeded.organization_id,
                    SourceHealthRow.brand_id == seeded.brand_id,
                    SourceHealthRow.source_type.in_(sources),
                )
            ).scalars()
        )
        llm_cost = session.scalar(
            select(func.coalesce(func.sum(LLMCallRow.cost_usd), 0.0)).where(
                LLMCallRow.organization_id == seeded.organization_id,
                LLMCallRow.brand_id == seeded.brand_id,
                LLMCallRow.called_at >= started_at,
            )
        ) or 0.0
    latency = memory.query_llm_latency(
        seeded.slug,
        started_at,
        organization_id=seeded.organization_id,
    )
    failures: list[str] = []
    if result.failed_sources:
        failures.append("source failures: " + ", ".join(sorted(result.failed_sources)))
    if result.processed_count == 0:
        failures.append("zero signals processed")
    if total_volume == 0:
        failures.append("current-run dashboard volume is zero")
    if relevant_count == 0:
        failures.append("no current-run on-brand signals")
    if route_count == 0:
        failures.append("no current-run routes persisted")
    return DemoBrandPopulationSummary(
        brand=seeded.slug,
        sources=list(sources),
        processed=result.processed_count,
        skipped=result.skipped_count,
        health={row.source_type: row.status for row in health_rows},
        total_volume=int(total_volume),
        relevant_count=int(relevant_count),
        route_count=int(route_count),
        llm_cost_usd=float(llm_cost),
        llm_latency_ms=latency,
        failure_reason="; ".join(failures) or None,
    )


def _acquire_population_lock(
    memory: SqlMemory,
    organization_id: int,
    *,
    now: datetime | None = None,
) -> PopulationLease:
    workflow_id = f"demo-population:organization:{organization_id}"
    owner_token = str(uuid4())
    now = now or _utc_now()
    stale_before = now - LOCK_LEASE_DURATION
    with memory.session() as session:
        existing = session.execute(
            select(WorkflowJobRow).where(WorkflowJobRow.workflow_id == workflow_id)
        ).scalar_one_or_none()
        if existing is None:
            try:
                row = WorkflowJobRow(
                    workflow_id=workflow_id,
                    run_id=owner_token,
                    workflow_type=LOCK_WORKFLOW_TYPE,
                    organization_id=organization_id,
                    brand_id=None,
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
                session.commit()
                return PopulationLease(row.id, owner_token)
            except IntegrityError:
                session.rollback()
        updated = session.execute(
            update(WorkflowJobRow)
            .where(
                WorkflowJobRow.workflow_id == workflow_id,
                (
                    (WorkflowJobRow.status != "running")
                    | (WorkflowJobRow.updated_at < stale_before)
                ),
            )
            .values(run_id=owner_token, status="running", updated_at=now)
        )
        session.commit()
        if updated.rowcount == 1:
            job_id = session.execute(
                select(WorkflowJobRow.id).where(WorkflowJobRow.workflow_id == workflow_id)
            ).scalar_one()
            return PopulationLease(job_id, owner_token)
    raise DemoPopulationAlreadyRunningError(
        f"A demo population run is already active for organization ID {organization_id}"
    )


def _renew_population_lock(
    memory: SqlMemory,
    lease: PopulationLease,
    *,
    now: datetime | None = None,
) -> None:
    with memory.session() as session:
        updated = session.execute(
            update(WorkflowJobRow)
            .where(
                WorkflowJobRow.id == lease.job_id,
                WorkflowJobRow.run_id == lease.owner_token,
                WorkflowJobRow.status == "running",
            )
            .values(updated_at=now or _utc_now())
        )
        session.commit()
    if updated.rowcount != 1:
        raise DemoPopulationAlreadyRunningError("Demo population lease ownership was lost")


def _release_population_lock(
    memory: SqlMemory,
    lease: PopulationLease,
    status: str,
) -> bool:
    with memory.session() as session:
        updated = session.execute(
            update(WorkflowJobRow)
            .where(
                WorkflowJobRow.id == lease.job_id,
                WorkflowJobRow.run_id == lease.owner_token,
                WorkflowJobRow.status == "running",
            )
            .values(status=status, updated_at=_utc_now())
        )
        session.commit()
    return updated.rowcount == 1


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized.lower() not in seen:
            result.append(normalized)
            seen.add(normalized.lower())
    return result


def _string_values(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
