from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker
from temporalio.worker._workflow_instance import UnsandboxedWorkflowRunner

from resound.models import RawSignal
from resound.social import (
    AdapterLimits,
    AdapterResult,
    ApprovedSourceConfigFingerprint,
    PublicSource,
    ResolvedProcessingConfigSnapshot,
    ResolvedProviderEvidence,
    ResolvedPublicListeningRequest,
    ResolvedSourceConfigSnapshot,
)
from resound.workflows import public_listening, signal_processing
from resound.workflows.public_listening import (
    PublicListeningSourceActivityRequest,
    PublicListeningSyncWorkflow,
    public_listening_finalizer_activity,
    public_listening_source_activity,
)
from resound.workflows.signal_processing import (
    SignalProcessingRequest,
    SignalProcessingResult,
    process_signal_processing_activity,
)


@dataclass(frozen=True)
class ThreadOverlapRequest:
    sources: tuple[PublicListeningSourceActivityRequest, ...]
    signal: SignalProcessingRequest


@workflow.defn
class ThreadOverlapWorkflow:
    def __init__(self):
        self.responsive = False

    @workflow.query
    def is_responsive(self) -> bool:
        return self.responsive

    @workflow.run
    async def run(self, request: ThreadOverlapRequest) -> int:
        handles = [
            workflow.start_activity(
                public_listening_source_activity,
                source,
                start_to_close_timeout=timedelta(seconds=20),
                heartbeat_timeout=timedelta(seconds=2),
            )
            for source in request.sources
        ]
        handles.append(
            workflow.start_activity(
                process_signal_processing_activity,
                request.signal,
                start_to_close_timeout=timedelta(seconds=20),
                heartbeat_timeout=timedelta(seconds=2),
            )
        )
        await workflow.sleep(0.05)
        self.responsive = True
        await asyncio.gather(*handles)
        return len(handles)


def _snapshot(source: PublicSource) -> ResolvedSourceConfigSnapshot:
    digest = "a" * 64
    evidence = ResolvedProviderEvidence(
        actor_id="test/actor",
        build_id="build-id",
        build_number="1.0.0",
        provider_declared_input_schema_reference="test:input",
        provider_declared_input_schema_sha256=digest,
        provider_declared_output_schema_reference="test:output",
        provider_declared_output_schema_sha256=digest,
        fixture_derived_shape_reference="test:shape",
        fixture_derived_shape_sha256=digest,
        canary_required=False,
        charge_quantum_usd=Decimal("0.01"),
        minimum_call_charge_usd=Decimal("0.01"),
        conservative_request_cost_usd=Decimal("0.01"),
    )
    return ResolvedSourceConfigSnapshot(
        source=source,
        storage_platform=source.value,
        paths=(),
        provider_evidence=(evidence,),
        limits=AdapterLimits(),
        processing=ResolvedProcessingConfigSnapshot.create(
            brand_context="test",
            routing_config={},
            people_config={},
            model_profile=None,
        ),
        approval_fingerprint=ApprovedSourceConfigFingerprint(
            value=digest,
            approval_envelope_value=digest,
            manifest_version="1",
        ),
    )


def _request() -> ThreadOverlapRequest:
    snapshots = tuple(_snapshot(source) for source in PublicSource)
    return ThreadOverlapRequest(
        sources=tuple(
            PublicListeningSourceActivityRequest(1, 1, "brand", 1, "owner", snapshot)
            for snapshot in snapshots
        ),
        signal=SignalProcessingRequest(
            brand_slug="brand",
            raw_signal=RawSignal(
                source="test",
                external_id="signal",
                content="test",
                posted_at=datetime(2026, 7, 17),
            ),
            brand_context="test",
            routing_config={},
            people_config={},
        ),
    )


def test_real_temporal_sync_activities_overlap_and_workflow_loop_stays_responsive(monkeypatch):
    """Real service proof; skip honestly when the repository Temporal service is unavailable."""

    barrier = threading.Barrier(6)
    all_started = threading.Event()
    release = threading.Event()
    active_threads: set[int] = set()
    active_lock = threading.Lock()

    def block() -> None:
        with active_lock:
            active_threads.add(threading.get_ident())
            if len(active_threads) == 6:
                all_started.set()
        barrier.wait(timeout=10)
        while not release.wait(0.05):
            activity.heartbeat("blocked")

    def fake_source(request):
        block()
        snapshot = request.source
        return AdapterResult(
            source=snapshot.source,
            platform=snapshot.storage_platform,
            status="ok",
            paths=(),
            max_signals_per_source=snapshot.limits.max_signals_per_source,
            config_fingerprint=snapshot.approval_fingerprint,
        )

    def fake_process(request, **_kwargs):
        block()
        return SignalProcessingResult(status="processed", dedupe_key="test")

    monkeypatch.setattr(public_listening, "execute_public_listening_source", fake_source)
    monkeypatch.setattr(signal_processing, "process_signal", fake_process)

    async def run_proof() -> None:
        try:
            client = await Client.connect(
                "127.0.0.1:7233",
                data_converter=pydantic_data_converter,
            )
        except Exception as exc:
            pytest.skip(f"real Temporal service unavailable: {type(exc).__name__}")
        task_queue = f"task-4-proof-{uuid4()}"
        executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="resound-activity-proof")
        try:
            async with Worker(
                client,
                task_queue=task_queue,
                workflows=[ThreadOverlapWorkflow],
                activities=[public_listening_source_activity, process_signal_processing_activity],
                activity_executor=executor,
                max_concurrent_activities=6,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await client.start_workflow(
                    ThreadOverlapWorkflow.run,
                    _request(),
                    id=f"task-4-proof-{uuid4()}",
                    task_queue=task_queue,
                )
                assert await asyncio.to_thread(all_started.wait, 10)
                for _ in range(50):
                    if await handle.query(ThreadOverlapWorkflow.is_responsive):
                        break
                    await asyncio.sleep(0.02)
                else:
                    raise AssertionError("workflow event loop did not answer its timer/query")
                assert len(active_threads) == 6
                release.set()
                assert await handle.result() == 6
        finally:
            release.set()
            executor.shutdown(wait=True, cancel_futures=True)

    asyncio.run(run_proof())


def test_real_temporal_cancellation_acks_all_sources_before_finalizer(monkeypatch):
    started = threading.Event()
    started_sources: set[str] = set()
    acknowledged: dict[str, float] = {}
    finalizer_started: list[float] = []
    lock = threading.Lock()

    def cancellable_source(request):
        source = request.source.source.value
        with lock:
            started_sources.add(source)
            if len(started_sources) == 5:
                started.set()
        try:
            while True:
                activity.heartbeat({"source": source, "checkpoint": "waiting"})
                time.sleep(0.03)
        except BaseException:
            if source == "youtube":
                time.sleep(0.2)
            with lock:
                acknowledged[source] = time.monotonic()
            raise

    class FakeMemory:
        def finalize_workflow_job(self, **_kwargs):
            finalizer_started.append(time.monotonic())
            return True

    monkeypatch.setattr(public_listening, "execute_public_listening_source", cancellable_source)
    monkeypatch.setattr(public_listening, "SqlMemory", FakeMemory)

    snapshots = tuple(_snapshot(source) for source in PublicSource)
    request = ResolvedPublicListeningRequest(
        organization_id=1,
        brand_id=1,
        brand_slug="brand",
        workflow_job_id=1,
        owner_token="owner",
        sources=snapshots,
        selected_paths={source.value: () for source in PublicSource},
        fingerprints={
            snapshot.source.value: snapshot.approval_fingerprint for snapshot in snapshots
        },
    )

    async def run_proof() -> None:
        try:
            client = await Client.connect(
                "127.0.0.1:7233",
                data_converter=pydantic_data_converter,
            )
        except Exception as exc:
            pytest.skip(f"real Temporal service unavailable: {type(exc).__name__}")
        task_queue = f"task-4-cancel-{uuid4()}"
        executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="resound-activity-cancel")
        try:
            async with Worker(
                client,
                task_queue=task_queue,
                workflows=[PublicListeningSyncWorkflow],
                activities=[public_listening_source_activity, public_listening_finalizer_activity],
                activity_executor=executor,
                max_concurrent_activities=6,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                handle = await client.start_workflow(
                    PublicListeningSyncWorkflow.run,
                    request,
                    id=f"task-4-cancel-{uuid4()}",
                    task_queue=task_queue,
                )
                assert await asyncio.to_thread(started.wait, 10)
                await handle.cancel()
                with pytest.raises(Exception):
                    await handle.result()
                for _ in range(100):
                    if finalizer_started:
                        break
                    await asyncio.sleep(0.02)
                assert set(acknowledged) == {source.value for source in PublicSource}
                assert finalizer_started
                assert finalizer_started[0] >= max(acknowledged.values())
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    asyncio.run(run_proof())
