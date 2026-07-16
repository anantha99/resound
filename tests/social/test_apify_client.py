from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from resound.social.apify import ApifyClient


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

    run = client.run_actor("owner/actor", {"searches": ["brand"]})
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
