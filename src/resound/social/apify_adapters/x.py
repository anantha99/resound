"""Pinned X discovery contract (execution intentionally blocked)."""

from __future__ import annotations

from resound.social.apify_adapters.common import (
    ActorRunPlan,
    ParsedProviderSignal,
    actor_minimum_charge,
    canonical_http_url,
    clean_strings,
    exact_datetime,
    identity_for,
    nested_text,
    optional_text,
    require_approved,
    required_text,
)
from resound.social.contracts import SourcePath
from resound.social.registry import ACTOR_REGISTRY


class XAdapter:
    actor = ACTOR_REGISTRY["x_discovery"]
    enabled = False
    max_runs = 2

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
        )
