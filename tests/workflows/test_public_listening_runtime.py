from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from resound.social.common import (
    ProviderBudgetInvariantError,
    ProviderBuildMismatchError,
    ProviderConfigError,
    ProviderUsageError,
    UnresolvedActorStartError,
)
from resound.social.contracts import (
    ActorRole,
    AdapterComponentResult,
    AdapterLimits,
    ApprovedSourceConfigFingerprint,
    PublicSource,
    ResolvedPathConfig,
    ResolvedProcessingConfigSnapshot,
    ResolvedProviderEvidence,
    ResolvedSelector,
    ResolvedSourceConfigSnapshot,
    SelectorKind,
    SourcePath,
)
from resound.workflows import public_listening
from resound.workflows.public_listening import (
    PublicListeningSourceActivityRequest,
    SourceActivityCheckpoint,
    execute_public_listening_source,
)
from resound.workflows.signal_processing import SignalProcessingResult


class Memory:
    def __init__(self) -> None:
        self.renewals = 0
        self.health = []

    def renew_workflow_lease(self, **_kwargs) -> bool:
        self.renewals += 1
        return True

    def record_source_health(self, **kwargs) -> None:
        self.health.append(kwargs)


def _evidence(
    source: PublicSource,
    path: SourcePath,
    role: ActorRole,
    suffix: str,
) -> ResolvedProviderEvidence:
    digest = "a" * 64
    return ResolvedProviderEvidence(
        source=source,
        path=path,
        actor_role=role,
        actor_id=f"snapshot/{suffix}",
        build_id=f"build-{suffix}",
        build_number=f"number-{suffix}",
        provider_declared_input_schema_reference=f"schema:{suffix}:input",
        provider_declared_input_schema_sha256=digest,
        provider_declared_output_schema_reference=f"schema:{suffix}:output",
        provider_declared_output_schema_sha256=digest,
        fixture_derived_shape_reference=f"fixture:{suffix}",
        fixture_derived_shape_sha256=digest,
        canary_required=False,
        charge_quantum_usd=Decimal("0.01"),
        minimum_call_charge_usd=Decimal("0.02"),
        conservative_request_cost_usd=Decimal("0.03"),
    )


def _path(
    path: SourcePath,
    selectors: tuple[ResolvedSelector, ...] = (),
    *,
    max_items: int = 2,
) -> ResolvedPathConfig:
    comments = path.value.endswith("comments")
    return ResolvedPathConfig(
        path=path,
        selectors=selectors,
        actor_input_mode="test",
        max_items=max_items,
        max_parents=2 if comments else 1,
        max_comments_per_parent=2 if comments else 1,
        max_comments=2 if comments else 1,
        requested_row_maximum=max_items,
        derived_run_count=0 if comments else 1,
    )


def _snapshot(
    source: PublicSource,
    paths: tuple[ResolvedPathConfig, ...],
    evidence: tuple[ResolvedProviderEvidence, ...],
    *,
    max_comments_per_source: int = 5,
) -> ResolvedSourceConfigSnapshot:
    digest = "b" * 64
    return ResolvedSourceConfigSnapshot(
        source=source,
        storage_platform=source.value,
        paths=paths,
        provider_evidence=evidence,
        limits=AdapterLimits(
            max_signals_per_source=20,
            max_items_per_path=5,
            max_parents_per_path=2,
            max_comments_per_parent=2,
            max_comments_per_path=2,
            max_comments_per_source=max_comments_per_source,
            max_runs_per_source=10,
            max_cost_usd_per_source=Decimal("2.00"),
            page_size=10,
            deadline_reserve_seconds=5,
        ),
        processing=ResolvedProcessingConfigSnapshot.create(
            brand_context="runtime test",
            routing_config={},
            people_config={},
            model_profile=None,
        ),
        approval_fingerprint=ApprovedSourceConfigFingerprint(
            value=digest,
            approval_envelope_value=digest,
            manifest_version="test",
        ),
    )


def _request(snapshot: ResolvedSourceConfigSnapshot) -> PublicListeningSourceActivityRequest:
    return PublicListeningSourceActivityRequest(1, 2, "brand", 3, "owner", snapshot)


@pytest.fixture(autouse=True)
def runtime_boundaries(monkeypatch):
    heartbeats = []
    monkeypatch.setattr(
        SourceActivityCheckpoint,
        "load",
        classmethod(lambda _cls: SourceActivityCheckpoint()),
    )
    monkeypatch.setattr(public_listening.activity, "heartbeat", heartbeats.append)
    monkeypatch.setattr(public_listening.activity, "is_cancelled", lambda: False)
    monkeypatch.setattr(
        public_listening,
        "_activity_deadline_monotonic",
        lambda: time.monotonic() + 120,
    )
    signal_id = 0

    def process(_request, **_kwargs):
        nonlocal signal_id
        signal_id += 1
        return SignalProcessingResult("processed", f"key-{signal_id}", signal_id=signal_id)

    monkeypatch.setattr(public_listening, "process_signal", process)
    return heartbeats


def test_runtime_executes_exact_path_evidence_not_registry_or_tuple_order() -> None:
    discovery = SourcePath.OFFICIAL_DISCOVERY
    comments = SourcePath.OFFICIAL_COMMENTS
    comment_evidence = _evidence(
        PublicSource.INSTAGRAM,
        comments,
        ActorRole.COMMENTS,
        "comments",
    ).model_copy(
        update={
            "charge_quantum_usd": Decimal("0.25"),
            "minimum_call_charge_usd": Decimal("0.50"),
            "conservative_request_cost_usd": Decimal("0.50"),
        }
    )
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                discovery,
                (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),),
            ),
            _path(comments),
        ),
        # Deliberately put comment evidence first to prove tuple ordering is irrelevant.
        (
            comment_evidence,
            _evidence(PublicSource.INSTAGRAM, discovery, ActorRole.DISCOVERY, "discovery"),
        ),
    )
    actor_calls = []
    provider_calls = []

    class Client:
        def run_actor(self, actor_id, _actor_input, **kwargs):
            kwargs["reservation_callback"]()
            actor_calls.append((actor_id, kwargs))
            index = len(actor_calls)
            return {"id": f"run-{index}"}

        def wait_for_run(self, run, **kwargs):
            provider_calls.append(("poll", kwargs))
            kwargs["progress_callback"]()
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": "0.10",
                "defaultDatasetId": f"dataset-{run['id']}",
            }

        def fetch_dataset_items(self, dataset_id, **kwargs):
            provider_calls.append(("dataset", kwargs))
            if dataset_id.endswith("run-1"):
                return [
                    {
                        "id": "post-1",
                        "caption": "post",
                        "timestamp": "2026-07-17T01:02:03Z",
                        "url": "https://www.instagram.com/p/post-1/",
                    }
                ]
            return [
                {
                    "id": "comment-1",
                    "text": "comment",
                    "timestamp": "2026-07-17T02:02:03Z",
                    "commentUrl": "https://www.instagram.com/p/post-1/c/comment-1/",
                    "postUrl": "https://www.instagram.com/p/post-1/",
                }
            ]

    result = execute_public_listening_source(
        _request(snapshot), memory=Memory(), apify_client=Client()
    )

    assert [call[0] for call in actor_calls] == [
        "snapshot/discovery",
        "snapshot/comments",
    ]
    assert [call[1]["expected_build_id"] for call in actor_calls] == [
        "build-discovery",
        "build-comments",
    ]
    assert [call[1]["build_number"] for call in actor_calls] == [
        "number-discovery",
        "number-comments",
    ]
    assert [call[1]["max_total_charge_usd"] for call in actor_calls] == [
        Decimal("2.00"),
        Decimal("1.75"),
    ]
    assert [run.input_schema_reference for component in result.paths for run in component.runs] == [
        "schema:discovery:input",
        "schema:comments:input",
    ]
    assert all(call[1]["deadline_context"] is not None for call in actor_calls)
    assert all(call[1]["deadline_monotonic"] is not None for call in actor_calls)
    assert all(kwargs["deadline_context"] is not None for _, kwargs in provider_calls)


def test_tiktok_traverses_both_secondary_comment_datasets_and_enforces_source_cap() -> None:
    paths = (
        _path(
            SourcePath.OFFICIAL_DISCOVERY,
            (ResolvedSelector(kind=SelectorKind.PROFILE, value="acme"),),
            max_items=1,
        ),
        _path(
            SourcePath.MENTION_DISCOVERY,
            (ResolvedSelector(kind=SelectorKind.SEARCH, value="acme"),),
            max_items=1,
        ),
        _path(SourcePath.OFFICIAL_COMMENTS),
        _path(SourcePath.MENTION_COMMENTS),
    )
    evidence = tuple(
        _evidence(
            PublicSource.TIKTOK,
            path.path,
            ActorRole.COMMENTS_DATASET
            if path.path.value.endswith("comments")
            else ActorRole.DISCOVERY,
            path.path.value,
        )
        for path in paths
    )
    snapshot = _snapshot(
        PublicSource.TIKTOK,
        paths,
        evidence,
        max_comments_per_source=2,
    )
    secondary_calls = []

    class Client:
        run_number = 0

        def run_actor(self, _actor_id, _actor_input, **kwargs):
            kwargs["reservation_callback"]()
            self.run_number += 1
            return {"id": f"run-{self.run_number}"}

        def wait_for_run(self, run, **kwargs):
            kwargs["progress_callback"]()
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": "0.10",
                "defaultDatasetId": f"videos-{run['id']}",
            }

        def fetch_dataset_items(self, dataset_id, **kwargs):
            if dataset_id.startswith("videos-"):
                suffix = "official" if dataset_id.endswith("1") else "mention"
                return [
                    {
                        "id": f"video-{suffix}",
                        "text": f"video {suffix}",
                        "createTimeISO": "2026-07-17T01:02:03Z",
                        "webVideoUrl": f"https://www.tiktok.com/@acme/video/{suffix}",
                        "commentsDatasetUrl": (
                            f"https://api.apify.com/v2/datasets/comments-{suffix}/items"
                        ),
                    }
                ]
            secondary_calls.append((dataset_id, kwargs))
            return [
                {
                    "id": f"comment-{dataset_id}",
                    "text": "comment",
                    "createTimeISO": "2026-07-17T02:02:03Z",
                    "commentUrl": f"https://www.tiktok.com/comment/{dataset_id}",
                }
            ]

    result = execute_public_listening_source(
        _request(snapshot), memory=Memory(), apify_client=Client()
    )

    assert [item[0] for item in secondary_calls] == ["comments-official", "comments-mention"]
    assert [item[1]["dataset_url"] for item in secondary_calls] == [
        "https://api.apify.com/v2/datasets/comments-official/items",
        "https://api.apify.com/v2/datasets/comments-mention/items",
    ]
    comment_components = [item for item in result.paths if item.path.value.endswith("comments")]
    assert (
        sum(
            item.processed_count + item.resumed_count + item.duplicate_count
            for item in comment_components
        )
        == 2
    )
    assert comment_components[0].datasets[0].parent_identity_value == "video-official"
    assert comment_components[1].datasets[0].parent_identity_value == "video-mention"
    assert result.cap_reached


def test_checkpoint_resumes_acknowledged_run_without_starting_duplicate(monkeypatch) -> None:
    path = SourcePath.OFFICIAL_DISCOVERY
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path, (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),)
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )
    snapshot = snapshot.model_copy(
        update={"limits": snapshot.limits.model_copy(update={"max_runs_per_source": 1})}
    )
    checkpoint = SourceActivityCheckpoint(
        runs={
            "official_discovery:0": {
                "run": {"id": "known-run"},
                "charge_cap": "2.00",
                "usage_reconciled": False,
            }
        }
    )
    monkeypatch.setattr(
        SourceActivityCheckpoint,
        "load",
        classmethod(lambda _cls: checkpoint),
    )

    class Client:
        def run_actor(self, *_args, **_kwargs):
            raise AssertionError("checkpointed acknowledged Run must not start again")

        def wait_for_run(self, run, **_kwargs):
            assert run["id"] == "known-run"
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": "0.10",
                "defaultDatasetId": "known-dataset",
            }

        def fetch_dataset_items(self, _dataset_id, **_kwargs):
            return []

    result = execute_public_listening_source(
        _request(snapshot), memory=Memory(), apify_client=Client()
    )
    assert result.paths[0].runs[0].run_id == "known-run"
    assert checkpoint.reconciled_spend_usd == "0.10"


def test_unresolved_checkpoint_reservation_blocks_before_provider_call(monkeypatch) -> None:
    path = SourcePath.OFFICIAL_DISCOVERY
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path, (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),)
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )
    monkeypatch.setattr(
        SourceActivityCheckpoint,
        "load",
        classmethod(
            lambda _cls: SourceActivityCheckpoint(reservations={"official_discovery:0": "2.00"})
        ),
    )

    with pytest.raises(UnresolvedActorStartError):
        execute_public_listening_source(
            _request(snapshot),
            memory=Memory(),
            apify_client=object(),
        )


def test_resumed_processing_is_accounted_and_associated(monkeypatch) -> None:
    path = SourcePath.OFFICIAL_DISCOVERY
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path, (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),)
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )
    monkeypatch.setattr(
        public_listening,
        "process_signal",
        lambda *_args, **_kwargs: SignalProcessingResult(
            "resumed",
            "existing",
            signal_id=9,
            processing_state="resumed",
            resumed_count=1,
        ),
    )

    class Client:
        def run_actor(self, _actor_id, _actor_input, **kwargs):
            kwargs["reservation_callback"]()
            return {"id": "run"}

        def wait_for_run(self, run, **_kwargs):
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": "0.10",
                "defaultDatasetId": "dataset",
            }

        def fetch_dataset_items(self, _dataset_id, **_kwargs):
            return [
                {
                    "id": "post",
                    "caption": "post",
                    "timestamp": datetime(2026, 7, 17, tzinfo=UTC).isoformat(),
                    "url": "https://www.instagram.com/p/post/",
                }
            ]

    result = execute_public_listening_source(
        _request(snapshot), memory=Memory(), apify_client=Client()
    )
    assert result.resumed_count == 1
    assert result.paths[0].associations[0].processing_state == "resumed"


def test_completed_checkpoint_path_is_returned_without_provider_call(monkeypatch) -> None:
    path = SourcePath.OFFICIAL_DISCOVERY
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path, (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),)
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )
    component = AdapterComponentResult(path=path, status="ok", processed_count=1)
    monkeypatch.setattr(
        SourceActivityCheckpoint,
        "load",
        classmethod(
            lambda _cls: SourceActivityCheckpoint(
                completed_paths=[path.value],
                components={path.value: component.model_dump(mode="json")},
            )
        ),
    )
    result = execute_public_listening_source(
        _request(snapshot),
        memory=Memory(),
        apify_client=object(),
    )
    assert result.paths == (component,)


def test_cancellation_aborts_only_acknowledged_run_and_stops_later_effects(monkeypatch) -> None:
    path = SourcePath.OFFICIAL_DISCOVERY
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path,
                (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),),
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )
    cancelled = False
    aborts = []
    later_effects = []
    monkeypatch.setattr(public_listening.activity, "is_cancelled", lambda: cancelled)

    class Client:
        def run_actor(self, _actor_id, _actor_input, **kwargs):
            kwargs["reservation_callback"]()
            return {"id": "acknowledged-run"}

        def wait_for_run(self, _run, **kwargs):
            nonlocal cancelled
            cancelled = True
            kwargs["progress_callback"]()
            raise AssertionError("cancellation heartbeat must stop polling")

        def abort_run(self, run_id, **kwargs):
            aborts.append((run_id, kwargs))

        def fetch_dataset_items(self, *_args, **_kwargs):
            later_effects.append("dataset")
            return []

    monkeypatch.setattr(
        public_listening,
        "process_signal",
        lambda *_args, **_kwargs: later_effects.append("signal"),
    )

    with pytest.raises(asyncio.CancelledError):
        execute_public_listening_source(
            _request(snapshot),
            memory=Memory(),
            apify_client=Client(),
        )

    assert aborts == [("acknowledged-run", {"timeout_seconds": 5.0})]
    assert later_effects == []


def _two_run_snapshot() -> ResolvedSourceConfigSnapshot:
    path = SourcePath.MENTION_DISCOVERY
    return _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path,
                (
                    ResolvedSelector(kind=SelectorKind.HASHTAG, value="acme"),
                    ResolvedSelector(kind=SelectorKind.PROFILE, value="acme-profile"),
                ),
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )


def test_definite_actor_rejection_releases_reservation_but_remains_fatal(
    runtime_boundaries,
) -> None:
    starts = 0

    class Client:
        def run_actor(self, _actor_id, _actor_input, **kwargs):
            nonlocal starts
            starts += 1
            kwargs["reservation_callback"]()
            raise ProviderConfigError(422, "definite rejection")

    with pytest.raises(ProviderConfigError):
        execute_public_listening_source(
            _request(_two_run_snapshot()), memory=Memory(), apify_client=Client()
        )

    assert starts == 1
    assert runtime_boundaries[-1]["reservations"] == {}


@pytest.mark.parametrize(
    "error",
    [
        UnresolvedActorStartError("mention_discovery:0"),
        ProviderBuildMismatchError("wrong immutable build"),
    ],
)
def test_ambiguous_or_build_failure_retains_reservation_and_prevents_later_runs(
    runtime_boundaries,
    error: Exception,
) -> None:
    starts = 0

    class Client:
        def run_actor(self, _actor_id, _actor_input, **kwargs):
            nonlocal starts
            starts += 1
            kwargs["reservation_callback"]()
            raise error

    with pytest.raises(type(error)):
        execute_public_listening_source(
            _request(_two_run_snapshot()), memory=Memory(), apify_client=Client()
        )

    assert starts == 1
    assert runtime_boundaries[-1]["reservations"] == {"mention_discovery:0": "2.00"}


@pytest.mark.parametrize(
    ("usage", "error_type"),
    [("NaN", ProviderUsageError), ("3.00", ProviderBudgetInvariantError)],
)
def test_usage_and_budget_safety_failures_are_fatal_and_prevent_later_runs(
    usage: str,
    error_type: type[Exception],
) -> None:
    starts = 0

    class Client:
        def run_actor(self, _actor_id, _actor_input, **kwargs):
            nonlocal starts
            starts += 1
            kwargs["reservation_callback"]()
            return {"id": "run-1"}

        def wait_for_run(self, run, **_kwargs):
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": usage,
                "defaultDatasetId": "dataset",
            }

    with pytest.raises(error_type):
        execute_public_listening_source(
            _request(_two_run_snapshot()), memory=Memory(), apify_client=Client()
        )

    assert starts == 1


def test_failed_signal_processing_emits_typed_issue_and_failed_component(monkeypatch) -> None:
    path = SourcePath.OFFICIAL_DISCOVERY
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path,
                (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),),
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )
    monkeypatch.setattr(
        public_listening,
        "process_signal",
        lambda *_args, **_kwargs: SignalProcessingResult(
            "failed",
            "failed-key",
            signal_id=11,
            processing_state="failed",
            error_class="ClassificationFailure",
            error_message="classification failed",
        ),
    )

    class Client:
        def run_actor(self, _actor_id, _actor_input, **kwargs):
            kwargs["reservation_callback"]()
            return {"id": "run"}

        def wait_for_run(self, run, **_kwargs):
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": "0.10",
                "defaultDatasetId": "dataset",
            }

        def fetch_dataset_items(self, _dataset_id, **_kwargs):
            return [
                {
                    "id": "post",
                    "caption": "post",
                    "timestamp": "2026-07-17T01:02:03Z",
                    "url": "https://www.instagram.com/p/post/",
                }
            ]

    component = execute_public_listening_source(
        _request(snapshot), memory=Memory(), apify_client=Client()
    ).paths[0]

    assert component.status == "failed"
    assert component.issues[0].code == "signal_processing_failed"
    assert component.issues[0].issue_class == "ClassificationFailure"
    assert component.associations[0].processing_state == "failed"


def test_resumed_work_plus_failed_processing_is_partial(monkeypatch) -> None:
    path = SourcePath.OFFICIAL_DISCOVERY
    snapshot = _snapshot(
        PublicSource.INSTAGRAM,
        (
            _path(
                path,
                (ResolvedSelector(kind=SelectorKind.URL, value="https://instagram.com/acme"),),
            ),
        ),
        (_evidence(PublicSource.INSTAGRAM, path, ActorRole.DISCOVERY, "discovery"),),
    )
    results = iter(
        (
            SignalProcessingResult(
                "resumed",
                "resumed-key",
                signal_id=1,
                processing_state="resumed",
                resumed_count=1,
            ),
            SignalProcessingResult(
                "failed",
                "failed-key",
                signal_id=2,
                processing_state="failed",
                error_class="RouteFailure",
                error_message="route failed",
            ),
        )
    )
    monkeypatch.setattr(public_listening, "process_signal", lambda *_args, **_kwargs: next(results))

    class Client:
        def run_actor(self, _actor_id, _actor_input, **kwargs):
            kwargs["reservation_callback"]()
            return {"id": "run"}

        def wait_for_run(self, run, **_kwargs):
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": "0.10",
                "defaultDatasetId": "dataset",
            }

        def fetch_dataset_items(self, _dataset_id, **_kwargs):
            return [
                {
                    "id": f"post-{index}",
                    "caption": f"post {index}",
                    "timestamp": "2026-07-17T01:02:03Z",
                    "url": f"https://www.instagram.com/p/post-{index}/",
                }
                for index in (1, 2)
            ]

    component = execute_public_listening_source(
        _request(snapshot), memory=Memory(), apify_client=Client()
    ).paths[0]

    assert component.status == "partial"
    assert component.resumed_count == 1
    assert component.processed_count == 0
    assert [association.processing_state for association in component.associations] == [
        "resumed",
        "failed",
    ]
