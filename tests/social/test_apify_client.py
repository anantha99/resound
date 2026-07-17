from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx
import pytest

from resound.social.apify import ApifyClient, serialize_start_urls, validate_apify_dataset_url


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_waits_for_actor_success_before_dataset_fetch() -> None:
    clock = FakeClock()
    operations: list[str] = []
    poll_statuses = iter(
        [
            {"id": "run-1", "status": "RUNNING"},
            {"id": "run-1", "status": "SUCCEEDED", "defaultDatasetId": "dataset-final"},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        if request.url.path.endswith("/runs"):
            operations.append("start")
            assert request.url.params["waitForFinish"] == "60"
            return httpx.Response(
                201,
                json={
                    "data": {
                        "id": "run-1",
                        "status": "RUNNING",
                        "defaultDatasetId": "dataset-initial",
                        "buildId": "build-id",
                        "buildNumber": "1.2.3",
                    }
                },
            )
        if request.url.path == "/v2/actor-runs/run-1":
            operations.append("poll")
            return httpx.Response(200, json={"data": next(poll_statuses)})
        if request.url.path == "/v2/datasets/dataset-final/items":
            operations.append("dataset")
            assert request.url.params["clean"] == "true"
            return httpx.Response(200, json=[{"id": "item-1"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = ApifyClient(
        "secret-token",
        run_poll_timeout_seconds=10,
        run_poll_interval_seconds=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        transport=_transport(handler),
    )

    run = client.run_actor(
        "owner/actor",
        {"searches": ["brand"]},
        build_number="1.2.3",
        expected_build_id="build-id",
        max_total_charge_usd=Decimal("0.50"),
        reservation_callback=lambda: None,
    )
    completed = client.wait_for_run(run)
    items = client.fetch_dataset_items(completed["defaultDatasetId"])

    assert completed["status"] == "SUCCEEDED"
    assert completed["defaultDatasetId"] == "dataset-final"
    assert items == [{"id": "item-1"}]
    assert operations == ["start", "poll", "poll", "dataset"]
    assert clock.sleeps == [1, 1.5]


@pytest.mark.parametrize("status", ["FAILED", "ABORTED", "TIMED-OUT"])
def test_terminal_actor_failure_has_safe_run_diagnostics(status: str) -> None:
    token = "never-include-this-token"
    client = ApifyClient(token)

    with pytest.raises(RuntimeError) as exc_info:
        client.wait_for_run(
            {
                "id": "run-failed",
                "status": status,
                "defaultDatasetId": "dataset-failed",
            }
        )

    message = str(exc_info.value)
    assert status in message
    assert "run_id=run-failed" in message
    assert "dataset_id=dataset-failed" in message
    assert token not in message


def test_actor_poll_timeout_is_bounded_and_reports_latest_status() -> None:
    clock = FakeClock()
    heartbeat_count = 0
    status_request_timeouts: list[dict[str, float]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/actor-runs/run-slow"
        status_request_timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, json={"data": {"id": "run-slow", "status": "RUNNING"}})

    def heartbeat() -> None:
        nonlocal heartbeat_count
        heartbeat_count += 1

    client = ApifyClient(
        "secret-token",
        run_poll_timeout_seconds=3,
        run_poll_interval_seconds=2,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        transport=_transport(handler),
    )

    with pytest.raises(TimeoutError) as exc_info:
        client.wait_for_run(
            {
                "id": "run-slow",
                "status": "RUNNING",
                "defaultDatasetId": "dataset-slow",
            },
            progress_callback=heartbeat,
        )

    message = str(exc_info.value)
    assert "after 3s" in message
    assert "run_id=run-slow" in message
    assert "dataset_id=dataset-slow" in message
    assert "status=RUNNING" in message
    assert clock.now == 3
    assert clock.sleeps == [2, 1]
    assert heartbeat_count == 2
    assert len(status_request_timeouts) == 1
    assert set(status_request_timeouts[0].values()) == {1.0}


@pytest.mark.parametrize("value", [0, -1])
def test_actor_poll_settings_must_be_positive(value: float) -> None:
    with pytest.raises(RuntimeError, match="run_poll_timeout_seconds must be greater than zero"):
        ApifyClient("secret-token", run_poll_timeout_seconds=value)


def test_actor_start_sends_exact_build_decimal_and_reservation_before_post() -> None:
    operations: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        operations.append("post")
        assert request.url.params["build"] == "0.0.561"
        assert request.url.params["maxTotalChargeUsd"] == "0.500"
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "run-1",
                    "status": "READY",
                    "buildId": "build-id",
                    "buildNumber": "0.0.561",
                }
            },
        )

    client = ApifyClient("secret-token", transport=_transport(handler))
    run = client.run_actor(
        "clockworks/tiktok-scraper",
        {"searchQueries": ["Acme"]},
        build_number="0.0.561",
        expected_build_id="build-id",
        max_total_charge_usd=Decimal("0.500"),
        reservation_callback=lambda: operations.append("reserve"),
    )

    assert run["id"] == "run-1"
    assert operations == ["reserve", "post"]


def test_actor_start_rejects_returned_build_mismatch() -> None:
    client = ApifyClient(
        "secret-token",
        transport=_transport(
            lambda request: httpx.Response(
                201,
                json={
                    "data": {
                        "id": "run-1",
                        "buildId": "wrong-build",
                        "buildNumber": "1.2.3",
                    }
                },
            )
        ),
    )
    with pytest.raises(RuntimeError, match="unexpected immutable build ID"):
        client.run_actor(
            "owner/actor",
            {},
            build_number="1.2.3",
            expected_build_id="expected-build",
            max_total_charge_usd=Decimal("0.10"),
            reservation_callback=lambda: None,
        )


def test_deadline_and_cancellation_prevent_provider_calls() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = ApifyClient("secret-token", monotonic=lambda: 10, transport=_transport(handler))
    with pytest.raises(TimeoutError, match="before provider call"):
        client.run_actor(
            "owner/actor",
            {},
            build_number="1.2.3",
            expected_build_id="build-id",
            max_total_charge_usd=Decimal("0.10"),
            reservation_callback=lambda: None,
            deadline_monotonic=9,
        )
    with pytest.raises(RuntimeError, match="cancelled before provider call"):
        client.fetch_dataset_items("dataset", limit=1, cancellation_requested=lambda: True)
    assert called is False


def test_bounded_dataset_paging_never_requests_more_than_remaining_limit() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.params["offset"], request.url.params["limit"]))
        requested = int(request.url.params["limit"])
        return httpx.Response(200, json=[{"id": index} for index in range(requested)])

    client = ApifyClient("secret-token", transport=_transport(handler))
    items = client.fetch_dataset_items("dataset", limit=5, page_size=2)

    assert len(items) == 5
    assert requests == [("0", "2"), ("2", "2"), ("4", "1")]


def test_source_specific_url_serialization_and_exact_tiktok_dataset_url() -> None:
    assert serialize_start_urls("instagram", ["https://instagram.com/acme"]) == [
        "https://instagram.com/acme"
    ]
    assert serialize_start_urls("youtube", ["https://youtube.com/@acme"]) == [
        {"url": "https://youtube.com/@acme"}
    ]
    assert validate_apify_dataset_url(
        "https://api.apify.com/v2/datasets/comments-1/items?token=redacted",
        expected_dataset_id="comments-1",
    ) == "https://api.apify.com/v2/datasets/comments-1/items"
    with pytest.raises(ValueError, match="expected Apify dataset"):
        validate_apify_dataset_url(
            "https://example.com/v2/datasets/comments-1/items",
            expected_dataset_id="comments-1",
        )
