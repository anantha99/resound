"""Apify API client for public-listening source syncs."""

from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx

from resound.config import env
from resound.social import ApifyQueryConfig


class ApifyClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        timeout_seconds: float = 70.0,
        run_poll_timeout_seconds: float | None = None,
        run_poll_interval_seconds: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        transport: httpx.BaseTransport | None = None,
    ):
        self.token = token or env("APIFY_API_TOKEN") or env("APIFY_TOKEN")
        if not self.token:
            raise RuntimeError("Missing APIFY_API_TOKEN for public listening sync")
        self.timeout_seconds = timeout_seconds
        self.run_poll_timeout_seconds = _positive_float(
            "run_poll_timeout_seconds",
            run_poll_timeout_seconds,
            env_name="APIFY_RUN_POLL_TIMEOUT_SECONDS",
            default=600.0,
        )
        self.run_poll_interval_seconds = _positive_float(
            "run_poll_interval_seconds",
            run_poll_interval_seconds,
            env_name="APIFY_RUN_POLL_INTERVAL_SECONDS",
            default=2.0,
        )
        self.sleep = sleep
        self.monotonic = monotonic
        self.transport = transport

    def run_actor(
        self,
        actor_id: str,
        actor_input: dict[str, Any],
        *,
        build_number: str,
        expected_build_id: str,
        max_total_charge_usd: Decimal,
        reservation_callback: Callable[[], None],
        deadline_monotonic: float | None = None,
        deadline_reserve_seconds: float = 0,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        if cancellation_requested is not None and cancellation_requested():
            raise RuntimeError("Apify actor start cancelled before provider call")
        timeout = self._remaining_timeout(
            deadline_monotonic, "actor start", reserve_seconds=deadline_reserve_seconds
        )
        url = f"https://api.apify.com/v2/acts/{apify_actor_path_id(actor_id)}/runs"
        params = {"waitForFinish": "60"}
        if not build_number.strip() or not expected_build_id.strip():
            raise ValueError("immutable build ID and number must be non-empty")
        params["build"] = build_number
        if max_total_charge_usd <= 0:
            raise ValueError("max_total_charge_usd must be greater than zero")
        params["maxTotalChargeUsd"] = format(max_total_charge_usd, "f")
        reservation_callback()
        with self._client(timeout_seconds=timeout) as client:
            response = client.post(url, params=params, json=actor_input, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise RuntimeError("Apify actor run response did not include run data")
        _verify_run_build(
            data,
            expected_build_id=expected_build_id,
            expected_build_number=build_number,
        )
        return data

    def wait_for_run(
        self,
        run: dict[str, Any],
        *,
        progress_callback: Callable[[], None] | None = None,
        deadline_monotonic: float | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        cancellation_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Poll an actor run until it succeeds or reaches a terminal failure."""
        current = dict(run)
        run_id = str(current.get("id") or "").strip()
        if not run_id:
            raise RuntimeError(f"Apify run is missing id ({_run_diagnostics(current)})")
        deadline = self.monotonic() + self.run_poll_timeout_seconds
        if deadline_monotonic is not None:
            deadline = min(deadline, deadline_monotonic)
        interval = self.run_poll_interval_seconds

        while True:
            if cancellation_requested is not None and cancellation_requested():
                if cancellation_callback is not None:
                    cancellation_callback(run_id)
                raise RuntimeError(f"Apify run polling cancelled ({_run_diagnostics(current)})")
            status = str(current.get("status") or "").upper()
            if status == "SUCCEEDED":
                return current
            if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                raise RuntimeError(
                    f"Apify run reached terminal status {status} ({_run_diagnostics(current)})"
                )
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Timed out waiting for Apify run to finish "
                    f"after {self.run_poll_timeout_seconds:g}s ({_run_diagnostics(current)})"
                )
            if progress_callback is not None:
                progress_callback()
            self.sleep(min(interval, remaining))
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "Timed out waiting for Apify run to finish "
                    f"after {self.run_poll_timeout_seconds:g}s ({_run_diagnostics(current)})"
                )
            request_timeout = min(self.timeout_seconds, remaining)
            request_timeout = max(request_timeout, min(0.001, remaining))
            current = _merge_run_data(
                current,
                self.get_run(run_id, timeout_seconds=request_timeout),
            )
            interval = min(interval * 1.5, 10.0)

    def get_run(
        self,
        run_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        url = f"https://api.apify.com/v2/actor-runs/{run_id}"
        with self._client(timeout_seconds=timeout_seconds) as client:
            response = client.get(url, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise RuntimeError(f"Apify run status response was invalid (run_id={run_id})")
        return data

    def fetch_dataset_items(
        self,
        dataset_id: str,
        *,
        limit: int | None = None,
        page_size: int = 100,
        deadline_monotonic: float | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
        dataset_url: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit is None:
            return self._fetch_dataset_page(
                dataset_id,
                offset=0,
                limit=None,
                deadline_monotonic=deadline_monotonic,
                cancellation_requested=cancellation_requested,
                dataset_url=dataset_url,
            )
        if limit <= 0 or page_size <= 0:
            raise ValueError("dataset limit and page_size must be greater than zero")
        items: list[dict[str, Any]] = []
        while len(items) < limit:
            requested = min(page_size, limit - len(items))
            page = self._fetch_dataset_page(
                dataset_id,
                offset=len(items),
                limit=requested,
                deadline_monotonic=deadline_monotonic,
                cancellation_requested=cancellation_requested,
                dataset_url=dataset_url,
            )
            items.extend(page[:requested])
            if len(page) < requested:
                break
        return items

    def _fetch_dataset_page(
        self,
        dataset_id: str,
        *,
        offset: int,
        limit: int | None,
        deadline_monotonic: float | None,
        cancellation_requested: Callable[[], bool] | None,
        dataset_url: str | None,
    ) -> list[dict[str, Any]]:
        if cancellation_requested is not None and cancellation_requested():
            raise RuntimeError("Apify dataset fetch cancelled before provider call")
        timeout = self._remaining_timeout(deadline_monotonic, "dataset fetch")
        url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
        if dataset_url is not None:
            url = validate_apify_dataset_url(dataset_url, expected_dataset_id=dataset_id)
        params = {"clean": "true"}
        if limit is not None:
            params.update({"offset": str(offset), "limit": str(limit)})
        with self._client(timeout_seconds=timeout) as client:
            response = client.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Apify dataset response was not a list")
        return [item for item in payload if isinstance(item, dict)]

    def _remaining_timeout(
        self,
        deadline_monotonic: float | None,
        operation: str,
        *,
        reserve_seconds: float = 0,
    ) -> float:
        if deadline_monotonic is None:
            return self.timeout_seconds
        remaining = deadline_monotonic - self.monotonic() - reserve_seconds
        if remaining <= 0:
            raise TimeoutError(f"Apify {operation} deadline elapsed before provider call")
        return min(self.timeout_seconds, remaining)

    def _client(self, *, timeout_seconds: float | None = None) -> httpx.Client:
        timeout = self.timeout_seconds if timeout_seconds is None else timeout_seconds
        return httpx.Client(timeout=timeout, transport=self.transport)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _positive_float(
    parameter_name: str,
    value: float | None,
    *,
    env_name: str,
    default: float,
) -> float:
    raw = value if value is not None else env(env_name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{parameter_name} must be a number") from exc
    if value <= 0:
        raise RuntimeError(f"{parameter_name} must be greater than zero")
    return value


def _merge_run_data(previous: dict[str, Any], latest: dict[str, Any]) -> dict[str, Any]:
    return {**previous, **{key: value for key, value in latest.items() if value is not None}}


def _run_diagnostics(run: dict[str, Any]) -> str:
    run_id = str(run.get("id") or "unknown")
    dataset_id = str(run.get("defaultDatasetId") or run.get("default_dataset_id") or "unknown")
    status = str(run.get("status") or "unknown")
    return f"run_id={run_id}, dataset_id={dataset_id}, status={status}"


def _verify_run_build(
    run: dict[str, Any], *, expected_build_id: str | None, expected_build_number: str | None
) -> None:
    if expected_build_id is not None:
        actual_id = str(run.get("buildId") or run.get("build_id") or "")
        if actual_id != expected_build_id:
            raise RuntimeError("Apify Run returned an unexpected immutable build ID")
    if expected_build_number is not None:
        actual_number = str(run.get("buildNumber") or run.get("build_number") or "")
        if actual_number != expected_build_number:
            raise RuntimeError("Apify Run returned an unexpected immutable build number")


def apify_actor_path_id(actor_id: str) -> str:
    return actor_id.replace("/", "~")


def serialize_start_urls(source_type: str, urls: list[str]) -> list[str] | list[dict[str, str]]:
    """Serialize URL selectors according to the captured actor input schema."""

    cleaned = [url.strip() for url in urls if isinstance(url, str) and url.strip()]
    if source_type in {"youtube", "youtube_comments"}:
        return [{"url": url} for url in cleaned]
    if source_type in {
        "reddit",
        "instagram",
        "instagram_public",
        "tiktok",
        "x",
        "x_public",
    }:
        return cleaned
    raise ValueError(f"Unsupported Apify public source type: {source_type}")


def validate_apify_dataset_url(url: str, *, expected_dataset_id: str) -> str:
    """Accept TikTok's exact commentsDatasetUrl only for the expected Apify dataset."""

    parsed = httpx.URL(url)
    expected_path = f"/v2/datasets/{expected_dataset_id}/items"
    if parsed.scheme != "https" or parsed.host != "api.apify.com" or parsed.path != expected_path:
        raise ValueError("dataset URL is not the expected Apify dataset items URL")
    return str(parsed.copy_with(query=None))


def apify_actor_input(config: ApifyQueryConfig, *, max_items: int = 100) -> dict[str, Any]:
    max_items = max(1, max_items)
    if config.source_type == "reddit":
        return _reddit_actor_input(config, max_items=max_items)
    if config.source_type == "instagram_public":
        return _instagram_actor_input(config, max_items=max_items)
    if config.source_type == "tiktok":
        return _tiktok_actor_input(config, max_items=max_items)
    if config.source_type == "x_public":
        return _x_actor_input(config, max_items=max_items)
    if config.source_type == "youtube_comments":
        return _youtube_actor_input(config, max_items=max_items)

    raise ValueError(f"Unsupported Apify public source type: {config.source_type}")


def _reddit_actor_input(config: ApifyQueryConfig, *, max_items: int) -> dict[str, Any]:
    configured_subreddits = config.source_settings.get("subreddits", [])
    subreddits = (
        [
            value.strip()
            for value in configured_subreddits
            if isinstance(value, str) and value.strip()
        ]
        if isinstance(configured_subreddits, list)
        else []
    )
    return {
        "subreddits": subreddits,
        "searches": config.query_terms,
        "startUrls": [],
        "searchPosts": True,
        "searchComments": False,
        "searchCommunities": False,
        "searchUsers": False,
        "sort": "new",
        "time": "month",
        "includeNSFW": False,
        "skipComments": True,
        "skipUserPosts": False,
        "skipUserComments": False,
        "skipCommunityInfo": True,
        "maxItems": max_items,
        "maxComments": 25,
        "maxCommentDepth": 2,
    }


def _instagram_actor_input(config: ApifyQueryConfig, *, max_items: int) -> dict[str, Any]:
    return {
        "resultsType": "posts",
        "directUrls": [],
        "search": ", ".join(config.query_terms),
        "searchType": "user",
        "searchLimit": 1,
        "resultsLimit": max_items,
        "onlyPostsNewerThan": "1 month",
        "addParentData": True,
    }


def _tiktok_actor_input(config: ApifyQueryConfig, *, max_items: int) -> dict[str, Any]:
    return {
        "searchQueries": config.query_terms,
        "resultsPerPage": _per_query_item_cap(config, max_items),
        "profileScrapeSections": ["videos"],
        "profileSorting": "latest",
        "excludePinnedPosts": True,
        "searchSection": "/video",
        "maxProfilesPerQuery": 10,
        "videoSearchSorting": "MOST_RELEVANT",
        "videoSearchDateFilter": "ALL_TIME",
        "scrapeRelatedSearchWords": False,
        "scrapeRelatedVideos": False,
        "scrapeAdditionalAuthorMeta": False,
        "shouldDownloadVideos": False,
        "shouldDownloadCovers": False,
        "shouldDownloadSlideshowImages": False,
        "shouldDownloadAvatars": False,
        "shouldDownloadMusicCovers": False,
        "downloadSubtitlesOptions": "NEVER_DOWNLOAD_SUBTITLES",
        "commentsPerPost": 0,
        "topLevelCommentsPerPost": 0,
        "maxRepliesPerComment": 0,
        "proxyCountryCode": "None",
    }


def _x_actor_input(config: ApifyQueryConfig, *, max_items: int) -> dict[str, Any]:
    return {
        "startUrls": [],
        "searchTerms": _x_search_terms(config),
        "twitterHandles": [],
        "maxItems": max_items,
        "sort": "Latest",
        "includeSearchTerms": True,
    }


def _youtube_actor_input(config: ApifyQueryConfig, *, max_items: int) -> dict[str, Any]:
    return {
        "searchQueries": config.query_terms,
        "maxResults": _per_query_item_cap(config, max_items),
        "maxResultsShorts": 0,
        "maxResultStreams": 0,
        "sortingOrder": "date",
        "dateFilter": "month",
        "videoType": "video",
    }


def _x_search_terms(config: ApifyQueryConfig) -> list[str]:
    excluded = " ".join(f"-{term}" for term in config.excluded_terms)
    language = f"lang:{config.language}" if config.language else ""
    suffix = " ".join(value for value in (excluded, language) if value)
    if not suffix:
        return config.query_terms
    return [f"{term} {suffix}" for term in config.query_terms]


def _per_query_item_cap(config: ApifyQueryConfig, max_items: int) -> int:
    query_count = max(1, len(config.query_terms))
    return max(1, (max_items + query_count - 1) // query_count)
