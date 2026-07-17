"""YouTube video-only official and mention discovery adapter."""

from __future__ import annotations

from resound.social.apify_adapters.common import (
    ActorRunPlan,
    ParsedProviderSignal,
    actor_minimum_charge,
    canonical_http_url,
    clean_strings,
    exact_datetime,
    identity_for,
    optional_text,
    required_text,
)
from resound.social.contracts import SourcePath
from resound.social.registry import ACTOR_REGISTRY


class YouTubeAdapter:
    actor = ACTOR_REGISTRY["youtube_discovery"]
    max_runs = 2

    def plan_official(self, *, channel_urls: list[str], max_items: int) -> tuple[ActorRunPlan, ...]:
        urls = clean_strings(channel_urls, field="startUrls")
        if not urls:
            return ()
        payload = {
            "startUrls": [{"url": url} for url in urls],
            "maxResults": max_items,
            "maxResultsShorts": 0,
            "maxResultStreams": 0,
            "sortingOrder": "date",
        }
        return (self._plan(SourcePath.OFFICIAL_DISCOVERY, payload, max_items),)

    def plan_mentions(
        self, *, search_queries: list[str], max_items: int
    ) -> tuple[ActorRunPlan, ...]:
        queries = clean_strings(search_queries, field="searchQueries")
        if not queries:
            return ()
        payload = {
            "searchQueries": queries,
            "maxResults": max_items,
            "maxResultsShorts": 0,
            "maxResultStreams": 0,
            "sortingOrder": "date",
        }
        return (self._plan(SourcePath.MENTION_DISCOVERY, payload, max_items),)

    def _plan(self, path: SourcePath, payload: dict[str, object], max_items: int) -> ActorRunPlan:
        if max_items <= 0:
            raise ValueError("max_items must be greater than zero")
        forbidden = {"comments", "subtitles", "download", "transcript", "ai"}
        if any(any(token in key.lower() for token in forbidden) for key in payload):
            raise ValueError("YouTube adapter must not request comments, media, subtitles, or AI")
        return ActorRunPlan(path, self.actor, payload, max_items, actor_minimum_charge(self.actor))

    @staticmethod
    def parse(item: dict[str, object]) -> ParsedProviderSignal:
        title = required_text(item, "title")
        description = optional_text(item, "description", "text")
        content = f"{title}\n\n{description}" if description and description != title else title
        timestamp = exact_datetime(
            item.get("date") or item.get("publishedAt"), field="date/publishedAt"
        )
        url = canonical_http_url(item.get("url"), field="url")
        return ParsedProviderSignal(
            platform="youtube",
            content_kind="video",
            identity=identity_for(
                native_id=item.get("id") or item.get("videoId"),
                platform="youtube",
                content_kind="video",
                canonical_url=url,
                provider_timestamp=timestamp,
                content=content,
            ),
            content=content,
            provider_timestamp=timestamp,
            canonical_url=url,
            author_handle=optional_text(item, "channelName", "channelId"),
        )
