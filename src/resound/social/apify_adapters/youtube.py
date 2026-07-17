"""YouTube video-only official and mention discovery adapter."""

from __future__ import annotations

from resound.social.apify_adapters.common import (
    ActorRunPlan,
    AdapterPathPlan,
    ParentContext,
    ParsedProviderSignal,
    SelectorKind,
    TypedSelector,
    actor_minimum_charge,
    canonical_http_url,
    clean_strings,
    exact_datetime,
    identity_for,
    observed_metrics,
    optional_text,
    required_text,
)
from resound.social.contracts import SourcePath
from resound.social.registry import ACTOR_REGISTRY


class YouTubeAdapter:
    actor = ACTOR_REGISTRY["youtube_discovery"]
    max_runs = 2

    def plan_path(
        self,
        *,
        path: SourcePath,
        selectors: tuple[TypedSelector, ...] = (),
        parents: tuple[ParsedProviderSignal, ...] = (),
        item_cap: int,
        max_parents: int,
        max_comments_per_parent: int,
        max_comments: int,
    ) -> AdapterPathPlan:
        del parents, max_parents, max_comments_per_parent, max_comments
        expected = (
            SelectorKind.URL if path == SourcePath.OFFICIAL_DISCOVERY else SelectorKind.SEARCH
        )
        if path not in {SourcePath.OFFICIAL_DISCOVERY, SourcePath.MENTION_DISCOVERY}:
            raise ValueError("YouTube supports discovery paths only")
        invalid = [selector.kind.value for selector in selectors if selector.kind != expected]
        if invalid:
            raise ValueError(f"unsupported YouTube selector kind(s): {', '.join(invalid)}")
        values = [selector.value for selector in selectors]
        runs = (
            self.plan_official(channel_urls=values, max_items=item_cap)
            if path == SourcePath.OFFICIAL_DISCOVERY
            else self.plan_mentions(search_queries=values, max_items=item_cap)
        )
        return AdapterPathPlan(path, actor_runs=runs)

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
            observed_public_metrics=observed_metrics(
                item,
                {
                    "views": ("viewCount", "views"),
                    "likes": ("likes", "likeCount"),
                    "comments": ("commentsCount", "commentCount"),
                },
            ),
        )

    def parse_path_result(
        self,
        *,
        path: SourcePath,
        item: dict[str, object],
        parent: ParentContext | None = None,
    ) -> ParsedProviderSignal:
        del path, parent
        return self.parse(item)
