"""Pinned X discovery contract (execution intentionally blocked)."""

from __future__ import annotations

from resound.social.apify_adapters.common import (
    ActorRunPlan,
    AdapterPathPlan,
    ParentContext,
    ParsedProviderSignal,
    TypedSelector,
    actor_minimum_charge,
    canonical_http_url,
    clean_strings,
    exact_datetime,
    identity_for,
    nested_text,
    observed_metrics,
    optional_text,
    require_approved,
    required_text,
)
from resound.social.contracts import SelectorKind, SourcePath
from resound.social.registry import ACTOR_REGISTRY


class XAdapter:
    actor = ACTOR_REGISTRY["x_discovery"]
    enabled = False
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
        allowed = (
            {SelectorKind.HANDLE, SelectorKind.URL}
            if path == SourcePath.OFFICIAL_DISCOVERY
            else {SelectorKind.SEARCH, SelectorKind.URL}
        )
        invalid = [selector.kind.value for selector in selectors if selector.kind not in allowed]
        if invalid:
            raise ValueError(f"unsupported X selector kind(s): {', '.join(invalid)}")
        runs = self.plan(
            path=path,
            twitter_handles=[x.value for x in selectors if x.kind == SelectorKind.HANDLE],
            search_terms=[x.value for x in selectors if x.kind == SelectorKind.SEARCH],
            start_urls=[x.value for x in selectors if x.kind == SelectorKind.URL],
            max_items=item_cap,
        )
        return AdapterPathPlan(path, actor_runs=runs)

    def plan(
        self,
        *,
        path: SourcePath,
        twitter_handles: list[str] | None = None,
        search_terms: list[str] | None = None,
        start_urls: list[str] | None = None,
        max_items: int,
    ) -> tuple[ActorRunPlan, ...]:
        require_approved(self.enabled, "x")
        if path not in {SourcePath.OFFICIAL_DISCOVERY, SourcePath.MENTION_DISCOVERY}:
            raise ValueError("X supports discovery paths only")
        payload = self.serialize_input(
            twitter_handles=twitter_handles or [],
            search_terms=search_terms or [],
            start_urls=start_urls or [],
            max_items=max_items,
        )
        return (
            ActorRunPlan(path, self.actor, payload, max_items, actor_minimum_charge(self.actor)),
        )

    @staticmethod
    def serialize_input(
        *,
        twitter_handles: list[str],
        search_terms: list[str],
        start_urls: list[str],
        max_items: int,
    ) -> dict[str, object]:
        if max_items <= 0:
            raise ValueError("max_items must be greater than zero")
        return {
            "twitterHandles": clean_strings(twitter_handles, field="twitterHandles"),
            "searchTerms": clean_strings(search_terms, field="searchTerms"),
            "startUrls": clean_strings(start_urls, field="startUrls"),
            "maxItems": max_items,
            "sort": "Latest",
        }

    @staticmethod
    def parse(item: dict[str, object]) -> ParsedProviderSignal:
        content = required_text(item, "text", "fullText")
        timestamp = exact_datetime(item.get("createdAt"), field="createdAt")
        url = canonical_http_url(item.get("url") or item.get("twitterUrl"), field="url")
        return ParsedProviderSignal(
            platform="x",
            content_kind="post",
            identity=identity_for(
                native_id=item.get("id") or item.get("tweetId"),
                platform="x",
                content_kind="post",
                canonical_url=url,
                provider_timestamp=timestamp,
                content=content,
            ),
            content=content,
            provider_timestamp=timestamp,
            canonical_url=url,
            author_handle=nested_text(item, "author", "userName", "username")
            or optional_text(item, "authorUsername"),
            observed_public_metrics=observed_metrics(
                item,
                {
                    "likes": ("likeCount",),
                    "replies": ("replyCount",),
                    "reposts": ("retweetCount",),
                    "views": ("viewCount",),
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
