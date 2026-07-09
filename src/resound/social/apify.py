"""Apify API client for public-listening source syncs."""

from __future__ import annotations

from typing import Any

import httpx

from resound.config import env
from resound.social import ApifyQueryConfig


class ApifyClient:
    def __init__(self, token: str | None = None, *, timeout_seconds: float = 60.0):
        self.token = token or env("APIFY_API_TOKEN") or env("APIFY_TOKEN")
        if not self.token:
            raise RuntimeError("Missing APIFY_API_TOKEN for public listening sync")
        self.timeout_seconds = timeout_seconds

    def run_actor(self, actor_id: str, actor_input: dict[str, Any]) -> dict[str, Any]:
        url = f"https://api.apify.com/v2/acts/{apify_actor_path_id(actor_id)}/runs"
        params = {"waitForFinish": "120"}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(url, params=params, json=actor_input, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise RuntimeError("Apify actor run response did not include run data")
        return data

    def fetch_dataset_items(self, dataset_id: str) -> list[dict[str, Any]]:
        url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
        params = {"clean": "true"}
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Apify dataset response was not a list")
        return [item for item in payload if isinstance(item, dict)]

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def apify_actor_path_id(actor_id: str) -> str:
    return actor_id.replace("/", "~")


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
    return {
        "subreddits": [],
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
