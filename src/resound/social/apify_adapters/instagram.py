"""Instagram string-URL discovery and bounded flat comment topology."""

from __future__ import annotations

from dataclasses import dataclass

from resound.social.apify_adapters.common import (
    ActorRunPlan,
    ParsedProviderSignal,
    actor_minimum_charge,
    canonical_http_url,
    clean_strings,
    exact_datetime,
    identity_for,
    optional_text,
    positive_quotient,
    required_text,
)
from resound.social.contracts import SourcePath
from resound.social.registry import ACTOR_REGISTRY


@dataclass(frozen=True)
class InstagramMentionSelector:
    value: str
    search_type: str = "hashtag"

    def __post_init__(self) -> None:
        if self.search_type not in {"hashtag", "user", "place", "profile"}:
            raise ValueError("Instagram supports only hashtag/profile/place/user selectors")
        if not self.value.strip():
            raise ValueError("Instagram selector cannot be empty")


class InstagramAdapter:
    discovery_actor = ACTOR_REGISTRY["instagram_discovery"]
    comments_actor = ACTOR_REGISTRY["instagram_comments"]
    max_official_selectors = 2
    max_mention_selectors = 6
    worst_case_runs = 9
    hard_run_ceiling = 10

    def plan_official(self, *, direct_urls: list[str], item_cap: int) -> tuple[ActorRunPlan, ...]:
        urls = clean_strings(direct_urls, field="directUrls")
        if len(urls) > self.max_official_selectors:
            raise ValueError("Instagram official selectors exceed hard cap 2")
        if not urls:
            return ()
        results_limit = positive_quotient(item_cap, len(urls), label="official discovery")
        payload = {
            "directUrls": urls,
            "resultsType": "posts",
            "resultsLimit": results_limit,
            "addParentData": True,
        }
        return (
            ActorRunPlan(
                SourcePath.OFFICIAL_DISCOVERY,
                self.discovery_actor,
                payload,
                results_limit * len(urls),
                actor_minimum_charge(self.discovery_actor),
            ),
        )

    def plan_mentions(
        self, *, selectors: list[InstagramMentionSelector], item_cap: int
    ) -> tuple[ActorRunPlan, ...]:
        if len(selectors) > self.max_mention_selectors:
            raise ValueError("Instagram mention selectors exceed hard cap 6")
        if not selectors:
            return ()
        results_limit = positive_quotient(item_cap, len(selectors), label="mention discovery")
        plans = []
        for selector in selectors:
            plans.append(
                ActorRunPlan(
                    SourcePath.MENTION_DISCOVERY,
                    self.discovery_actor,
                    {
                        "search": selector.value.strip(),
                        "searchType": selector.search_type,
                        "searchLimit": 1,
                        "resultsType": "posts",
                        "resultsLimit": results_limit,
                        "addParentData": True,
                    },
                    results_limit,
                    actor_minimum_charge(self.discovery_actor),
                )
            )
        return tuple(plans)

    def plan_comments(
        self,
        *,
        path: SourcePath,
        parent_urls: list[str],
        path_comment_cap: int,
        max_comments_per_parent: int,
    ) -> tuple[ActorRunPlan, ...]:
        if path not in {SourcePath.OFFICIAL_COMMENTS, SourcePath.MENTION_COMMENTS}:
            raise ValueError("Instagram comment planner requires a flat comment path")
        urls = clean_strings(parent_urls, field="directUrls")
        if not urls:
            return ()
        quotient = positive_quotient(path_comment_cap, len(urls), label=path.value)
        results_limit = min(max_comments_per_parent, quotient)
        payload = {
            "directUrls": urls,
            "resultsLimit": results_limit,
            "includeNestedComments": False,
        }
        return (
            ActorRunPlan(
                path,
                self.comments_actor,
                payload,
                results_limit * len(urls),
                actor_minimum_charge(self.comments_actor),
            ),
        )

    def validate_run_count(self, plans: tuple[ActorRunPlan, ...], *, max_runs: int) -> None:
        if len(plans) > min(max_runs, self.hard_run_ceiling):
            raise ValueError("Instagram derived actor Run count exceeds effective maximum")

    @staticmethod
    def parse_post(item: dict[str, object]) -> ParsedProviderSignal:
        content = required_text(item, "caption", "text")
        timestamp = exact_datetime(item.get("timestamp"), field="timestamp")
        url = canonical_http_url(item.get("url"), field="url")
        return ParsedProviderSignal(
            platform="instagram",
            content_kind="post",
            identity=identity_for(
                native_id=item.get("id") or item.get("shortCode"),
                platform="instagram",
                content_kind="post",
                canonical_url=url,
                provider_timestamp=timestamp,
                content=content,
            ),
            content=content,
            provider_timestamp=timestamp,
            canonical_url=url,
            author_handle=optional_text(item, "ownerUsername", "username"),
        )

    @staticmethod
    def parse_comment(item: dict[str, object]) -> ParsedProviderSignal:
        content = required_text(item, "text", "commentText")
        timestamp = exact_datetime(item.get("timestamp"), field="timestamp")
        comment_url = canonical_http_url(item.get("commentUrl"), field="commentUrl", required=True)
        parent_url = canonical_http_url(item.get("postUrl"), field="postUrl", required=True)
        return ParsedProviderSignal(
            platform="instagram",
            content_kind="comment",
            identity=identity_for(
                native_id=item.get("id"),
                platform="instagram",
                content_kind="comment",
                canonical_url=comment_url,
                provider_timestamp=timestamp,
                content=content,
            ),
            content=content,
            provider_timestamp=timestamp,
            canonical_url=comment_url,
            parent_url=parent_url,
            author_handle=optional_text(item, "ownerUsername", "username"),
        )
