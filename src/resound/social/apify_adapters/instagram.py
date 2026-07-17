"""Instagram string-URL discovery and bounded flat comment topology."""

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
    observed_metrics,
    optional_text,
    positive_quotient,
    required_text,
)
from resound.social.contracts import SelectorKind, SourcePath
from resound.social.registry import ACTOR_REGISTRY


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
        self, *, selectors: list[TypedSelector], item_cap: int
    ) -> tuple[ActorRunPlan, ...]:
        if len(selectors) > self.max_mention_selectors:
            raise ValueError("Instagram mention selectors exceed hard cap 6")
        if not selectors:
            return ()
        results_limit = positive_quotient(item_cap, len(selectors), label="mention discovery")
        plans = []
        for selector in selectors:
            if selector.kind not in {
                SelectorKind.HASHTAG,
                SelectorKind.PROFILE,
                SelectorKind.PLACE,
                SelectorKind.USER,
            }:
                raise ValueError("Instagram supports only hashtag/profile/place/user selectors")
            plans.append(
                ActorRunPlan(
                    SourcePath.MENTION_DISCOVERY,
                    self.discovery_actor,
                    {
                        "search": selector.value,
                        "searchType": selector.kind.value,
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
        if path == SourcePath.OFFICIAL_DISCOVERY:
            urls = self._selector_values(selectors, {SelectorKind.URL})
            return AdapterPathPlan(
                path, actor_runs=self.plan_official(direct_urls=urls, item_cap=item_cap)
            )
        if path == SourcePath.MENTION_DISCOVERY:
            return AdapterPathPlan(
                path, actor_runs=self.plan_mentions(selectors=list(selectors), item_cap=item_cap)
            )
        parent_urls = [
            parent.canonical_url for parent in parents[:max_parents] if parent.canonical_url
        ]
        plans = self.plan_comments(
            path=path,
            parent_urls=parent_urls,
            path_comment_cap=max_comments,
            max_comments_per_parent=max_comments_per_parent,
        )
        return AdapterPathPlan(
            path,
            actor_runs=plans,
            empty_reason="no_eligible_parents" if not plans else None,
        )

    @staticmethod
    def _selector_values(
        selectors: tuple[TypedSelector, ...], allowed: set[SelectorKind]
    ) -> list[str]:
        invalid = [selector.kind.value for selector in selectors if selector.kind not in allowed]
        if invalid:
            raise ValueError(f"unsupported Instagram selector kind(s): {', '.join(invalid)}")
        return [selector.value for selector in selectors]

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
            observed_public_metrics=observed_metrics(
                item,
                {
                    "likes": ("likesCount", "likeCount"),
                    "comments": ("commentsCount",),
                    "views": ("videoViewCount", "videoPlayCount"),
                },
            ),
        )

    @staticmethod
    def parse_comment(
        item: dict[str, object], *, parent: ParentContext | None = None
    ) -> ParsedProviderSignal:
        content = required_text(item, "text", "commentText")
        timestamp = exact_datetime(item.get("timestamp"), field="timestamp")
        comment_url = canonical_http_url(item.get("commentUrl"), field="commentUrl", required=True)
        parent_url = canonical_http_url(item.get("postUrl"), field="postUrl", required=True)
        parent_context = parent or ParentContext(
            platform="instagram",
            content_kind="post",
            author_handle=optional_text(item, "postOwnerUsername", "parentAuthorUsername"),
            excerpt=optional_text(item, "postCaption", "parentCaption"),
            canonical_url=parent_url,
            published_at=(
                exact_datetime(item.get("postTimestamp"), field="postTimestamp")
                if item.get("postTimestamp") is not None
                else None
            ),
            provider_native_id=optional_text(item, "postId", "parentId"),
        )
        if parent_context.canonical_url != parent_url:
            raise ValueError("Instagram postUrl does not match the associated parent")
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
            parent_context=parent_context,
            author_handle=optional_text(item, "ownerUsername", "username"),
            observed_public_metrics=observed_metrics(
                item, {"likes": ("likesCount", "likeCount"), "replies": ("repliesCount",)}
            ),
        )

    def parse_path_result(
        self,
        *,
        path: SourcePath,
        item: dict[str, object],
        parent: ParentContext | None = None,
    ) -> ParsedProviderSignal:
        if path in {SourcePath.OFFICIAL_COMMENTS, SourcePath.MENTION_COMMENTS}:
            return self.parse_comment(item, parent=parent)
        return self.parse_post(item)


def InstagramMentionSelector(value: str, search_type: str = "hashtag") -> TypedSelector:  # noqa: N802
    """Compatibility constructor returning the shared typed selector contract."""

    try:
        kind = SelectorKind(search_type)
    except ValueError as exc:
        raise ValueError("Instagram supports only hashtag/profile/place/user selectors") from exc
    return TypedSelector(kind=kind, value=value)
