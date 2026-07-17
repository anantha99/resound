from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from resound.cli import app
from resound.gateway import (
    DEMO_POPULATION_MODEL_PROFILE,
    DEMO_POPULATION_RELIABLE_MODEL_PROFILE,
    LLMResponse,
)
from resound.memory import (
    BrandRow,
    ClassificationRow,
    ListeningProfileRow,
    LLMCallRow,
    OrganizationRow,
    RouteRow,
    SignalRow,
    SourceHealthRow,
    SqlMemory,
    WorkflowJobRow,
)
from resound.models import ActionClass, Classification, RawSignal, Route, Sentiment, Severity
from resound.ops.demo_population import (
    DemoPopulationAlreadyRunningError,
    _acquire_population_lock,
    _release_population_lock,
    _renew_population_lock,
    brand_search_terms,
    populate_demo_brands,
    seed_demo_brands,
    validate_demo_brands,
)
from resound.workflows.public_listening import sync_public_listening
from resound.workflows.signal_processing import SignalProcessingRequest, process_signal


def _memory(tmp_path: Path) -> SqlMemory:
    return SqlMemory(database_url=f"sqlite:///{tmp_path / 'demo-population.db'}")


def _count(memory: SqlMemory, row_type) -> int:
    with memory.session() as session:
        return session.scalar(select(func.count()).select_from(row_type)) or 0


def _sync_classifications(is_about_brand_values: list[bool]):
    class ProcessedResult:
        processed_count = len(is_about_brand_values)
        skipped_count = 0
        failed_sources = {}

    def sync_fn(request, *, memory, progress_callback):
        progress_callback()
        for index, is_about_brand in enumerate(is_about_brand_values):
            signal_id = memory.record_signal(
                request.brand_slug,
                RawSignal(
                    source="reddit",
                    external_id=f"relevance-{index}-{is_about_brand}",
                    content=f"Relevance fixture {index}",
                    posted_at=datetime.now(UTC),
                ),
                organization_id=request.tenant.organization_id,
                brand_id=request.brand_id,
            )
            classification_id = memory.record_classification(
                signal_id,
                Classification(
                    is_about_brand=is_about_brand,
                    area="product",
                    sentiment=Sentiment.NEGATIVE,
                    severity=Severity.MEDIUM,
                    action_class=(ActionClass.SPRINT if is_about_brand else ActionClass.IGNORE),
                    summary=f"Relevance fixture {index}",
                    confidence=0.9,
                ),
            )
            memory.record_route(
                signal_id,
                classification_id,
                Route(owner_id="#triage", matched_rule="relevance-fixture"),
            )
        return ProcessedResult()

    return sync_fn


def test_seed_demo_brands_is_idempotent_and_preserves_reddit_config(tmp_path):
    memory = _memory(tmp_path)

    first = seed_demo_brands(memory)
    second = seed_demo_brands(memory)

    assert [item.slug for item in first] == ["liquiddeath", "notion"]
    assert [item.brand_id for item in second] == [item.brand_id for item in first]
    assert _count(memory, OrganizationRow) == 1
    assert _count(memory, BrandRow) == 2
    assert _count(memory, ListeningProfileRow) == 2
    expected = {
        "liquiddeath": (["liquiddeath"], ["liquid death", "liquiddeath"]),
        "notion": (
            ["Notion", "productivity", "startups"],
            ["Notion", "Notion AI", "Notion outage"],
        ),
    }
    for item in second:
        profile = memory.get_listening_profile(
            organization_id=item.organization_id,
            brand_id=item.brand_id,
            brand_slug=item.slug,
        )
        assert profile is not None
        assert profile.source_config["reddit"]["subreddits"] == expected[item.slug][0]
        assert profile.source_config["reddit"]["search_terms"] == expected[item.slug][1]


def test_scalar_brand_search_terms_are_not_split_into_characters():
    cfg = SimpleNamespace(sources={"reddit": {"search_terms": "Notion outage"}})

    assert brand_search_terms(cfg) == ["Notion outage"]


def test_default_brand_selection_fails_if_an_approved_bundle_is_missing(tmp_path):
    liquiddeath = tmp_path / "liquiddeath"
    liquiddeath.mkdir()
    (liquiddeath / "brand.yaml").write_text('name: "Liquid Death"\n')

    with pytest.raises(FileNotFoundError, match="notion"):
        validate_demo_brands(None, tmp_path)


def test_dry_run_does_not_create_database_or_call_sync(tmp_path, monkeypatch):
    db_path = tmp_path / "dry-run.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    called = False

    def sync_fn(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("dry-run must not sync")

    summary = populate_demo_brands(dry_run=True, sync_fn=sync_fn)

    assert summary.mode == "dry-run"
    assert [item.brand for item in summary.brands] == ["liquiddeath", "notion"]
    assert called is False
    assert not db_path.exists()


def test_seed_only_writes_only_org_brand_and_profile_rows(tmp_path):
    memory = _memory(tmp_path)

    summary = populate_demo_brands(memory=memory, seed_only=True)

    assert summary.succeeded
    assert _count(memory, OrganizationRow) == 1
    assert _count(memory, BrandRow) == 2
    assert _count(memory, ListeningProfileRow) == 2
    for row_type in (
        SignalRow,
        ClassificationRow,
        RouteRow,
        SourceHealthRow,
        LLMCallRow,
        WorkflowJobRow,
    ):
        assert _count(memory, row_type) == 0


def test_zero_processed_marks_brand_failed(tmp_path):
    memory = _memory(tmp_path)

    class EmptyResult:
        processed_count = 0
        skipped_count = 0
        failed_sources = {}

    summary = populate_demo_brands(
        memory=memory,
        brands=["liquiddeath"],
        sync_fn=lambda *args, **kwargs: EmptyResult(),
    )

    assert summary.succeeded is False
    assert "zero signals processed" in summary.brands[0].failure_reason
    assert "current-run dashboard volume is zero" in summary.brands[0].failure_reason
    assert "no current-run on-brand signals" in summary.brands[0].failure_reason
    assert "no current-run routes persisted" in summary.brands[0].failure_reason


def test_all_current_run_off_brand_classifications_fail_population(tmp_path):
    summary = populate_demo_brands(
        memory=_memory(tmp_path),
        brands=["liquiddeath"],
        sync_fn=_sync_classifications([False, False]),
    )

    result = summary.brands[0]
    assert summary.succeeded is False
    assert result.processed == 2
    assert result.total_volume == 2
    assert result.route_count == 2
    assert result.relevant_count == 0
    assert result.failure_reason == "no current-run on-brand signals"


def test_mixed_current_run_relevant_and_ignored_classifications_succeed(tmp_path):
    summary = populate_demo_brands(
        memory=_memory(tmp_path),
        brands=["liquiddeath"],
        sync_fn=_sync_classifications([False, True]),
    )

    result = summary.brands[0]
    assert summary.succeeded
    assert result.processed == 2
    assert result.total_volume == 2
    assert result.route_count == 2
    assert result.relevant_count == 1
    assert result.failure_reason is None


def test_default_mode_targets_only_two_demo_brands_and_honors_item_cap(tmp_path):
    memory = _memory(tmp_path)
    requests = []

    class EmptyResult:
        processed_count = 0
        skipped_count = 0
        failed_sources = {}

    def sync_fn(request, **kwargs):
        requests.append(request)
        return EmptyResult()

    populate_demo_brands(
        memory=memory,
        max_items=7,
        continue_on_error=True,
        sync_fn=sync_fn,
    )

    assert [request.brand_slug for request in requests] == ["liquiddeath", "notion"]
    assert all(request.enabled_sources == ["reddit"] for request in requests)
    assert all(request.max_items_per_source == 7 for request in requests)
    assert all(request.model_profile == DEMO_POPULATION_MODEL_PROFILE for request in requests)


def test_reliable_classifier_selects_sonnet_primary_profile_for_both_brands(tmp_path):
    memory = _memory(tmp_path)
    requests = []

    class EmptyResult:
        processed_count = 0
        skipped_count = 0
        failed_sources = {}

    def sync_fn(request, **kwargs):
        requests.append(request)
        return EmptyResult()

    populate_demo_brands(
        memory=memory,
        reliable_classifier=True,
        continue_on_error=True,
        sync_fn=sync_fn,
    )

    assert [request.brand_slug for request in requests] == ["liquiddeath", "notion"]
    assert all(
        request.model_profile == DEMO_POPULATION_RELIABLE_MODEL_PROFILE for request in requests
    )


def test_population_profile_reaches_gateway_construction_for_both_brands(
    tmp_path,
    monkeypatch,
):
    memory = _memory(tmp_path)
    gateway_calls = []

    class FakeApifyClient:
        def run_actor(self, actor_id, actor_input):
            return {"id": actor_id, "status": "SUCCEEDED", "defaultDatasetId": actor_id}

        def wait_for_run(self, run, *, progress_callback=None):
            if progress_callback is not None:
                progress_callback()
            return run

        def fetch_dataset_items(self, dataset_id):
            return [
                {
                    "id": f"{dataset_id}-item-{index}",
                    "text": "A current product issue needs review.",
                    "createdAt": datetime.now(UTC).isoformat(),
                    "url": f"https://example.com/{dataset_id}/{index}",
                }
                for index in range(2)
            ]

    class FakeGateway:
        def complete(self, stage, prompt, response_schema=None):
            return LLMResponse(
                content=(
                    '{"is_about_brand": true, "area": "product", '
                    '"sentiment": "negative", "severity": "medium", '
                    '"action_class": "sprint", "summary": "Product issue", '
                    '"confidence": 0.9}'
                ),
                model_used="fake/demo-profile",
                tokens_in=1,
                tokens_out=1,
                cost_usd=0.0,
                latency_ms=1.0,
                raw_response={},
            )

        def complete_validated(self, stage, prompt, response_schema, validator):
            response = self.complete(stage, prompt, response_schema)
            validator(response.content)
            return response

    def fake_build_gateway(brand_slug, profile=None):
        gateway_calls.append((brand_slug, profile))
        return FakeGateway()

    monkeypatch.setattr("resound.agents.signal_triage.build_gateway", fake_build_gateway)

    def run_sync(request, *, memory, progress_callback):
        return sync_public_listening(
            request,
            memory=memory,
            apify_client=FakeApifyClient(),
            progress_callback=progress_callback,
        )

    summary = populate_demo_brands(
        memory=memory,
        continue_on_error=True,
        sync_fn=run_sync,
    )

    assert summary.succeeded
    assert gateway_calls == [
        ("liquiddeath", DEMO_POPULATION_MODEL_PROFILE),
        ("notion", DEMO_POPULATION_MODEL_PROFILE),
    ]
    assert [brand.processed for brand in summary.brands] == [2, 2]


def test_historical_volume_and_routes_do_not_satisfy_current_run(tmp_path):
    memory = _memory(tmp_path)
    seeded = seed_demo_brands(memory, brands=["liquiddeath"])[0]
    signal_id = memory.record_signal(
        "liquiddeath",
        RawSignal(
            source="reddit",
            external_id="historical",
            content="Historical useful signal",
            posted_at=datetime.now(UTC),
        ),
        organization_id=seeded.organization_id,
        brand_id=seeded.brand_id,
    )
    classification_id = memory.record_classification(
        signal_id,
        Classification(
            is_about_brand=True,
            area="product",
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.MEDIUM,
            action_class=ActionClass.SPRINT,
            summary="Historical issue",
            confidence=0.9,
        ),
    )
    memory.record_route(
        signal_id,
        classification_id,
        Route(owner_id="#triage", matched_rule="historical"),
    )

    class MisleadingResult:
        processed_count = 1
        skipped_count = 0
        failed_sources = {}

    summary = populate_demo_brands(
        memory=memory,
        brands=["liquiddeath"],
        sync_fn=lambda *args, **kwargs: MisleadingResult(),
    )

    result = summary.brands[0]
    assert result.total_volume == 0
    assert result.relevant_count == 0
    assert result.route_count == 0
    assert "current-run dashboard volume is zero" in result.failure_reason
    assert "no current-run on-brand signals" in result.failure_reason
    assert "no current-run routes persisted" in result.failure_reason


def test_historical_relevant_classification_does_not_satisfy_current_run(tmp_path):
    memory = _memory(tmp_path)
    seeded = seed_demo_brands(memory, brands=["liquiddeath"])[0]
    signal_id = memory.record_signal(
        "liquiddeath",
        RawSignal(
            source="reddit",
            external_id="historical-relevant",
            content="Historical on-brand signal",
            posted_at=datetime.now(UTC),
        ),
        organization_id=seeded.organization_id,
        brand_id=seeded.brand_id,
    )
    classification_id = memory.record_classification(
        signal_id,
        Classification(
            is_about_brand=True,
            area="product",
            sentiment=Sentiment.NEGATIVE,
            severity=Severity.MEDIUM,
            action_class=ActionClass.SPRINT,
            summary="Historical on-brand issue",
            confidence=0.9,
        ),
    )
    memory.record_route(
        signal_id,
        classification_id,
        Route(owner_id="#triage", matched_rule="historical-relevant"),
    )

    summary = populate_demo_brands(
        memory=memory,
        brands=["liquiddeath"],
        sync_fn=_sync_classifications([False]),
    )

    result = summary.brands[0]
    assert summary.succeeded is False
    assert result.total_volume == 1
    assert result.route_count == 1
    assert result.relevant_count == 0
    assert result.failure_reason == "no current-run on-brand signals"


def test_old_post_ingested_now_counts_as_current_run_dashboard_volume(tmp_path):
    memory = _memory(tmp_path)

    class ProcessedResult:
        processed_count = 1
        skipped_count = 0
        failed_sources = {}

    def sync_fn(request, *, memory, progress_callback):
        progress_callback()
        signal_id = memory.record_signal(
            request.brand_slug,
            RawSignal(
                source="reddit",
                external_id="old-post-new-ingestion",
                content="An older post discovered during this run",
                posted_at=datetime.now(UTC) - timedelta(days=60),
            ),
            organization_id=request.tenant.organization_id,
            brand_id=request.brand_id,
        )
        classification_id = memory.record_classification(
            signal_id,
            Classification(
                is_about_brand=True,
                area="product",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.MEDIUM,
                action_class=ActionClass.SPRINT,
                summary="Old but newly ingested",
                confidence=0.9,
            ),
        )
        memory.record_route(
            signal_id,
            classification_id,
            Route(owner_id="#triage", matched_rule="current-run"),
        )
        return ProcessedResult()

    summary = populate_demo_brands(
        memory=memory,
        brands=["liquiddeath"],
        sync_fn=sync_fn,
    )

    assert summary.succeeded
    assert summary.brands[0].total_volume == 1
    assert summary.brands[0].relevant_count == 1
    assert summary.brands[0].route_count == 1


def test_retry_of_preexisting_raw_only_signal_counts_current_classification_and_route(
    tmp_path,
):
    memory = _memory(tmp_path)
    seeded = seed_demo_brands(memory, brands=["liquiddeath"])[0]
    raw = RawSignal(
        source="reddit",
        external_id="raw-only-retry",
        content="A raw-only signal that should complete on retry",
        posted_at=datetime.now(UTC) - timedelta(days=30),
    )
    original_signal_id = memory.record_signal(
        "liquiddeath",
        raw,
        organization_id=seeded.organization_id,
        brand_id=seeded.brand_id,
    )
    with memory.session() as session:
        original = session.get(SignalRow, original_signal_id)
        original.ingested_at = datetime(2025, 1, 1)
        session.commit()

    class RetryClassifier:
        def classify(self, raw_signal, brand_context):
            return (
                Classification(
                    is_about_brand=True,
                    area="product",
                    sentiment=Sentiment.NEGATIVE,
                    severity=Severity.MEDIUM,
                    action_class=ActionClass.SPRINT,
                    summary="Completed on retry",
                    confidence=0.9,
                ),
                LLMResponse(
                    content="{}",
                    model_used="fake/retry",
                    tokens_in=1,
                    tokens_out=1,
                    cost_usd=0.0,
                    latency_ms=1.0,
                    raw_response={},
                ),
            )

    class ProcessedResult:
        processed_count = 1
        skipped_count = 0
        failed_sources = {}

    def retry_sync(request, *, memory, progress_callback):
        progress_callback()
        result = process_signal(
            SignalProcessingRequest(
                brand_slug=request.brand_slug,
                raw_signal=raw,
                brand_context=request.brand_context,
                routing_config=request.routing_config,
                people_config=request.people_config,
                organization_id=request.tenant.organization_id,
                brand_id=request.brand_id,
            ),
            memory=memory,
            classifier=RetryClassifier(),
        )
        assert result.status == "resumed"
        assert result.processing_state == "resumed"
        assert result.signal_id == original_signal_id
        return ProcessedResult()

    summary = populate_demo_brands(
        memory=memory,
        brands=["liquiddeath"],
        sync_fn=retry_sync,
    )

    assert summary.succeeded
    assert summary.brands[0].total_volume == 1
    assert summary.brands[0].relevant_count == 1
    assert summary.brands[0].route_count == 1
    assert _count(memory, SignalRow) == 1


def test_concurrent_population_is_rejected(tmp_path):
    memory = _memory(tmp_path)
    seeded = seed_demo_brands(memory, brands=["liquiddeath"])
    _acquire_population_lock(memory, seeded[0].organization_id)

    with pytest.raises(DemoPopulationAlreadyRunningError, match="already active"):
        populate_demo_brands(
            memory=memory,
            brands=["liquiddeath"],
            sync_fn=lambda *args, **kwargs: pytest.fail("sync must not run"),
        )


def test_lock_uses_canonical_organization_id_for_case_and_spacing_variants(tmp_path):
    memory = _memory(tmp_path)
    canonical_id = memory.ensure_organization(" Demo ", "Demo")
    variant_id = memory.ensure_organization("DEMO", "Demo")
    assert variant_id == canonical_id
    _acquire_population_lock(memory, canonical_id)

    with pytest.raises(DemoPopulationAlreadyRunningError, match=str(canonical_id)):
        _acquire_population_lock(memory, variant_id)


def test_stale_population_lease_is_reclaimed_and_old_owner_cannot_release(tmp_path):
    memory = _memory(tmp_path)
    organization_id = memory.ensure_organization("demo", "Demo")
    started = datetime(2026, 1, 1)
    old_lease = _acquire_population_lock(memory, organization_id, now=started)

    new_lease = _acquire_population_lock(
        memory,
        organization_id,
        now=started + timedelta(minutes=31),
    )

    assert new_lease.owner_token != old_lease.owner_token
    assert _release_population_lock(memory, old_lease, "failed") is False
    _renew_population_lock(memory, new_lease, now=started + timedelta(minutes=32))
    assert _release_population_lock(memory, new_lease, "completed") is True
    with memory.session() as session:
        row = session.get(WorkflowJobRow, new_lease.job_id)
        assert row.status == "completed"
        assert row.run_id == new_lease.owner_token


def test_fresh_population_lease_cannot_be_reclaimed(tmp_path):
    memory = _memory(tmp_path)
    organization_id = memory.ensure_organization("demo", "Demo")
    started = datetime(2026, 1, 1)
    _acquire_population_lock(memory, organization_id, now=started)

    with pytest.raises(DemoPopulationAlreadyRunningError):
        _acquire_population_lock(
            memory,
            organization_id,
            now=started + timedelta(minutes=29),
        )


def test_long_brand_run_heartbeats_prevent_stale_reclamation(tmp_path, monkeypatch):
    memory = _memory(tmp_path)
    start = datetime(2026, 1, 1)
    clock = [start]
    monkeypatch.setattr("resound.ops.demo_population._utc_now", lambda: clock[0])

    class ProcessedResult:
        processed_count = 1
        skipped_count = 0
        failed_sources = {}

    def long_sync(request, *, memory, progress_callback):
        for heartbeat_time, competing_time in (
            (start + timedelta(minutes=20), start + timedelta(minutes=39)),
            (start + timedelta(minutes=40), start + timedelta(minutes=59)),
            (start + timedelta(minutes=60), start + timedelta(minutes=79)),
        ):
            clock[0] = heartbeat_time
            progress_callback()
            with pytest.raises(DemoPopulationAlreadyRunningError):
                _acquire_population_lock(
                    memory,
                    request.tenant.organization_id,
                    now=competing_time,
                )
        signal_id = memory.record_signal(
            request.brand_slug,
            RawSignal(
                source="reddit",
                external_id="long-run-current",
                content="Long run completed with heartbeats",
                posted_at=datetime.now(UTC),
            ),
            organization_id=request.tenant.organization_id,
            brand_id=request.brand_id,
        )
        classification_id = memory.record_classification(
            signal_id,
            Classification(
                is_about_brand=True,
                area="product",
                sentiment=Sentiment.NEGATIVE,
                severity=Severity.MEDIUM,
                action_class=ActionClass.SPRINT,
                summary="Long run",
                confidence=0.9,
            ),
        )
        memory.record_route(
            signal_id,
            classification_id,
            Route(owner_id="#triage", matched_rule="long-run"),
        )
        return ProcessedResult()

    summary = populate_demo_brands(
        memory=memory,
        brands=["liquiddeath"],
        sync_fn=long_sync,
    )

    assert summary.succeeded


def test_heartbeat_ownership_loss_aborts_population(tmp_path):
    memory = _memory(tmp_path)

    def ownership_losing_sync(request, *, memory, progress_callback):
        with memory.session() as session:
            row = session.execute(
                select(WorkflowJobRow).where(
                    WorkflowJobRow.organization_id == request.tenant.organization_id,
                    WorkflowJobRow.status == "running",
                )
            ).scalar_one()
            row.run_id = "new-owner"
            session.commit()
        progress_callback()
        pytest.fail("ownership loss must stop synchronization")

    with pytest.raises(DemoPopulationAlreadyRunningError, match="ownership was lost"):
        populate_demo_brands(
            memory=memory,
            brands=["liquiddeath"],
            sync_fn=ownership_losing_sync,
        )


@pytest.mark.parametrize("max_items", [0, 101])
def test_max_items_is_bounded(max_items):
    with pytest.raises(ValueError, match="between 1 and 100"):
        populate_demo_brands(max_items=max_items, dry_run=True)


def test_unapproved_brand_is_rejected():
    with pytest.raises(ValueError, match="Unsupported demo brand"):
        populate_demo_brands(brands=["all"], dry_run=True)


def test_unsupported_source_is_rejected():
    with pytest.raises(ValueError, match="Unsupported public source"):
        populate_demo_brands(sources=["g2"], dry_run=True)


runner = CliRunner()


def test_cli_rejects_dry_run_with_seed_only():
    result = runner.invoke(app, ["populate-demo-brands", "--dry-run", "--seed-only"])

    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_cli_help_documents_reliable_classifier_live_fill_option():
    result = runner.invoke(app, ["populate-demo-brands", "--help"])

    assert result.exit_code == 0
    assert "--reliable-classifier" in result.output
    assert "Sonnet 5" in result.output


def test_cli_forwards_reliable_classifier(monkeypatch):
    summary = SimpleNamespace(
        organization="demo",
        mode="dry-run",
        brands=[],
        succeeded=True,
    )
    calls = []

    def fake_populate(**kwargs):
        calls.append(kwargs)
        return summary

    monkeypatch.setattr("resound.cli.populate_demo_brands", fake_populate)

    result = runner.invoke(
        app,
        ["populate-demo-brands", "--dry-run", "--reliable-classifier"],
    )

    assert result.exit_code == 0
    assert calls[0]["reliable_classifier"] is True


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--brand", "all", "--dry-run"], "Unsupported demo brand"),
        (["--max-items", "0", "--dry-run"], "1"),
        (["--max-items", "101", "--dry-run"], "100"),
    ],
)
def test_cli_rejects_invalid_brand_and_item_caps(args, message):
    result = runner.invoke(app, ["populate-demo-brands", *args])

    assert result.exit_code != 0
    assert message in result.output


@pytest.mark.parametrize("mode_flag", ["--strict", "--continue-on-error"])
def test_cli_failure_summary_exits_nonzero_for_strict_modes(monkeypatch, mode_flag):
    failed_brand = SimpleNamespace(
        brand="liquiddeath",
        sources=["reddit"],
        processed=0,
        skipped=0,
        health={},
        total_volume=0,
        relevant_count=0,
        route_count=0,
        llm_cost_usd=0.0,
        llm_latency_ms={},
        failure_reason="zero signals processed",
    )
    summary = SimpleNamespace(
        organization="demo",
        mode="populate",
        brands=[failed_brand],
        succeeded=False,
    )
    calls = []

    def fake_populate(**kwargs):
        calls.append(kwargs)
        return summary

    monkeypatch.setattr("resound.cli.populate_demo_brands", fake_populate)

    result = runner.invoke(app, ["populate-demo-brands", mode_flag])

    assert result.exit_code == 1
    assert "Demo population (populate)" in result.output
    assert calls[0]["continue_on_error"] is (mode_flag == "--continue-on-error")
