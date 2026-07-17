"""Pinned Reddit discovery contract (execution intentionally blocked)."""

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
    require_approved,
    required_text,
)
from resound.social.contracts import SourcePath
from resound.social.registry import ACTOR_REGISTRY


class RedditAdapter:
    actor = ACTOR_REGISTRY["reddit_discovery"]
    enabled = False
    max_runs = 2

    def plan(
        self,
        *,
        path: SourcePath,
        subreddits: list[str] | None = None,
        searches: list[str] | None = None,
        start_urls: list[str] | None = None,
        max_items: int,
    ) -> tuple[ActorRunPlan, ...]:
        require_approved(self.enabled, "reddit")
        if path not in {SourcePath.OFFICIAL_DISCOVERY, SourcePath.MENTION_DISCOVERY}:
            raise ValueError("Reddit supports discovery paths only")
        payload = self.serialize_input(
            subreddits=subreddits or [],
            searches=searches or [],
            start_urls=start_urls or [],
            max_items=max_items,
        )
        return (
            ActorRunPlan(path, self.actor, payload, max_items, actor_minimum_charge(self.actor)),
        )

    @staticmethod
    def serialize_input(
        *, subreddits: list[str], searches: list[str], start_urls: list[str], max_items: int
    ) -> dict[str, object]:
        if max_items <= 0:
            raise ValueError("max_items must be greater than zero")
        return {
            "subreddits": clean_strings(subreddits, field="subreddits"),
            "searches": clean_strings(searches, field="searches"),
            "startUrls": clean_strings(start_urls, field="startUrls"),
            "searchPosts": True,
            "skipComments": True,
            "maxItems": max_items,
        }

    @staticmethod
    def parse(item: dict[str, object]) -> ParsedProviderSignal:
        title = optional_text(item, "title", "postTitle")
        body = optional_text(item, "body", "text", "selftext")
        content = f"{title}\n\n{body}" if title and body and title != body else title or body
        if content is None:
            content = required_text(item, "title", "body", "text", "selftext")
        timestamp = exact_datetime(item.get("createdAt"), field="createdAt")
        url = canonical_http_url(item.get("url"), field="url")
        return ParsedProviderSignal(
            platform="reddit",
            content_kind="post",
            identity=identity_for(
                native_id=item.get("id"),
                platform="reddit",
                content_kind="post",
                canonical_url=url,
                provider_timestamp=timestamp,
                content=content,
            ),
            content=content,
            provider_timestamp=timestamp,
            canonical_url=url,
            author_handle=optional_text(item, "author", "username"),
        )
