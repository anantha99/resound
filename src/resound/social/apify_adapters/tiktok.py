"""TikTok two-Run discovery and authenticated secondary comment datasets."""

from __future__ import annotations

from urllib.parse import urlsplit

from resound.social.apify import ApifyClient, validate_apify_dataset_url
from resound.social.apify_adapters.common import (
    ActorRunPlan,
    AdapterPathPlan,
    DatasetFetchPlan,
    ParentContext,
    ParsedProviderSignal,
    ParserError,
    SelectorKind,
    TypedSelector,
    actor_minimum_charge,
    canonical_http_url,
    clean_strings,
    exact_datetime,
    identity_for,
    nested_text,
    observed_metrics,
    optional_text,
    positive_quotient,
    required_text,
)
from resound.social.contracts import SourcePath
from resound.social.registry import ACTOR_REGISTRY


class TikTokAdapter:
    actor = ACTOR_REGISTRY["tiktok"]
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
        if path == SourcePath.OFFICIAL_DISCOVERY:
            profiles = self._selector_values(selectors, {SelectorKind.PROFILE})
            return AdapterPathPlan(
                path,
                actor_runs=self.plan_official(
                    profiles=profiles,
                    item_cap=item_cap,
                    comments_per_post=max_comments_per_parent,
                ),
            )
        if path == SourcePath.MENTION_DISCOVERY:
            hashtags = self._selector_values(selectors, {SelectorKind.HASHTAG}, reject_other=False)
            searches = self._selector_values(selectors, {SelectorKind.SEARCH}, reject_other=False)
            invalid = [
                selector.kind.value
                for selector in selectors
                if selector.kind not in {SelectorKind.HASHTAG, SelectorKind.SEARCH}
            ]
            if invalid:
                raise ValueError(
                    f"unsupported TikTok mention selector kind(s): {', '.join(invalid)}"
                )
            return AdapterPathPlan(
                path,
                actor_runs=self.plan_mentions(
                    hashtags=hashtags,
                    search_queries=searches,
                    item_cap=item_cap,
                    comments_per_post=max_comments_per_parent,
                ),
            )
        if path not in {SourcePath.OFFICIAL_COMMENTS, SourcePath.MENTION_COMMENTS}:
            raise ValueError(f"unsupported TikTok path: {path.value}")
        fetches = self.plan_comment_datasets(
            path=path,
            parents=parents,
            max_parents=max_parents,
            max_comments_per_parent=max_comments_per_parent,
            max_comments=max_comments,
        )
        return AdapterPathPlan(
            path,
            dataset_fetches=fetches,
            empty_reason="no_eligible_parents" if not fetches else None,
        )

    @staticmethod
    def _selector_values(
        selectors: tuple[TypedSelector, ...],
        allowed: set[SelectorKind],
        *,
        reject_other: bool = True,
    ) -> list[str]:
        invalid = [selector.kind.value for selector in selectors if selector.kind not in allowed]
        if invalid and reject_other:
            raise ValueError(f"unsupported TikTok selector kind(s): {', '.join(invalid)}")
        return [selector.value for selector in selectors if selector.kind in allowed]

    def plan_official(
        self, *, profiles: list[str], item_cap: int, comments_per_post: int
    ) -> tuple[ActorRunPlan, ...]:
        return self._plan(
            path=SourcePath.OFFICIAL_DISCOVERY,
            selectors={"profiles": clean_strings(profiles, field="profiles")},
            item_cap=item_cap,
            comments_per_post=comments_per_post,
        )

    def plan_mentions(
        self,
        *,
        hashtags: list[str],
        search_queries: list[str],
        item_cap: int,
        comments_per_post: int,
    ) -> tuple[ActorRunPlan, ...]:
        return self._plan(
            path=SourcePath.MENTION_DISCOVERY,
            selectors={
                "hashtags": clean_strings(hashtags, field="hashtags"),
                "searchQueries": clean_strings(search_queries, field="searchQueries"),
            },
            item_cap=item_cap,
            comments_per_post=comments_per_post,
        )

    def _plan(
        self,
        *,
        path: SourcePath,
        selectors: dict[str, list[str]],
        item_cap: int,
        comments_per_post: int,
    ) -> tuple[ActorRunPlan, ...]:
        selector_count = sum(len(values) for values in selectors.values())
        if not selector_count:
            return ()
        results_per_page = positive_quotient(item_cap, selector_count, label=path.value)
        if comments_per_post <= 0:
            raise ValueError("comments_per_post must be greater than zero")
        payload: dict[str, object] = {key: values for key, values in selectors.items() if values}
        payload.update(
            {
                "resultsPerPage": results_per_page,
                "commentsPerPost": comments_per_post,
                "maxRepliesPerComment": 0,
            }
        )
        forbidden = ("download", "media", "subtitle", "transcript", "ai")
        if any(any(token in key.lower() for token in forbidden) for key in payload):
            raise ValueError("TikTok adapter must not request media, transcription, or AI")
        return (
            ActorRunPlan(
                path,
                self.actor,
                payload,
                results_per_page * selector_count,
                actor_minimum_charge(self.actor),
            ),
        )

    @staticmethod
    def comments_dataset_reference(comments_dataset_url: object) -> tuple[str, str]:
        if not isinstance(comments_dataset_url, str) or not comments_dataset_url.strip():
            raise ParserError("TikTok row is missing exact commentsDatasetUrl")
        parsed = urlsplit(comments_dataset_url.strip())
        parts = parsed.path.strip("/").split("/")
        if len(parts) != 4 or parts[:2] != ["v2", "datasets"] or parts[3] != "items":
            raise ParserError("TikTok commentsDatasetUrl is not an exact dataset items URL")
        dataset_id = parts[2]
        if not dataset_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in dataset_id
        ):
            raise ParserError("TikTok commentsDatasetUrl contains an invalid dataset ID")
        try:
            sanitized_url = validate_apify_dataset_url(
                comments_dataset_url, expected_dataset_id=dataset_id
            )
        except ValueError as exc:
            raise ParserError(str(exc)) from exc
        return dataset_id, sanitized_url

    @classmethod
    def plan_comment_datasets(
        cls,
        *,
        path: SourcePath,
        parents: tuple[ParsedProviderSignal, ...],
        max_parents: int,
        max_comments_per_parent: int,
        max_comments: int,
    ) -> tuple[DatasetFetchPlan, ...]:
        if path not in {SourcePath.OFFICIAL_COMMENTS, SourcePath.MENTION_COMMENTS}:
            raise ValueError("TikTok dataset traversal requires a flat comment path")
        eligible = [parent for parent in parents if parent.comments_dataset_url][:max_parents]
        if not eligible:
            return ()
        per_parent_limit = min(max_comments_per_parent, max_comments // len(eligible))
        if per_parent_limit <= 0:
            raise ValueError("TikTok comment cap cannot allocate one row to every eligible parent")
        plans = []
        for parent in eligible:
            dataset_id, dataset_url = cls.comments_dataset_reference(parent.comments_dataset_url)
            parent_context = parent.as_parent_context()
            plans.append(
                DatasetFetchPlan(
                    path=path,
                    dataset_id=dataset_id,
                    dataset_url=dataset_url,
                    requested_limit=per_parent_limit,
                    parent=parent_context,
                    provenance={
                        "source": "tiktok",
                        "path": path.value,
                        "association": "commentsDatasetUrl",
                        "parent_identity": parent.identity.value,
                    },
                )
            )
        return tuple(plans)

    @classmethod
    def fetch_comments(
        cls,
        client: ApifyClient,
        *,
        comments_dataset_url: str,
        limit: int,
        page_size: int,
    ) -> list[dict[str, object]]:
        dataset_id, exact_url = cls.comments_dataset_reference(comments_dataset_url)
        return client.fetch_dataset_items(
            dataset_id,
            dataset_url=exact_url,
            limit=limit,
            page_size=page_size,
        )

    @classmethod
    def parse_video(cls, item: dict[str, object]) -> ParsedProviderSignal:
        content = required_text(item, "text", "description", "desc")
        timestamp = exact_datetime(
            item.get("createTimeISO") or item.get("createTime"),
            field="createTimeISO/createTime",
        )
        url = canonical_http_url(item.get("webVideoUrl"), field="webVideoUrl")
        comments_url = optional_text(item, "commentsDatasetUrl")
        if comments_url is not None:
            cls.comments_dataset_reference(comments_url)
        return ParsedProviderSignal(
            platform="tiktok",
            content_kind="video",
            identity=identity_for(
                native_id=item.get("id"),
                platform="tiktok",
                content_kind="video",
                canonical_url=url,
                provider_timestamp=timestamp,
                content=content,
            ),
            content=content,
            provider_timestamp=timestamp,
            canonical_url=url,
            author_handle=nested_text(item, "authorMeta", "name", "nickName"),
            observed_public_metrics=observed_metrics(
                item,
                {
                    "likes": ("diggCount", "likes", "likeCount"),
                    "comments": ("commentCount", "comments"),
                    "shares": ("shareCount", "shares"),
                    "plays": ("playCount", "views"),
                },
            ),
            comments_dataset_url=comments_url,
        )

    @staticmethod
    def parse_comment(
        item: dict[str, object],
        *,
        parent: ParentContext | None = None,
        parent_url: str | None = None,
    ) -> ParsedProviderSignal:
        content = required_text(item, "text", "commentText")
        timestamp = exact_datetime(
            item.get("createTimeISO") or item.get("createTime"),
            field="createTimeISO/createTime",
        )
        if parent is None:
            canonical_parent = canonical_http_url(parent_url, field="parent_url", required=True)
            parent = ParentContext(
                platform="tiktok",
                content_kind="video",
                author_handle=None,
                excerpt=None,
                canonical_url=canonical_parent,
                published_at=None,
            )
        comment_url = canonical_http_url(item.get("commentUrl"), field="commentUrl")
        return ParsedProviderSignal(
            platform="tiktok",
            content_kind="comment",
            identity=identity_for(
                native_id=item.get("id") or item.get("cid"),
                platform="tiktok",
                content_kind="comment",
                canonical_url=comment_url,
                provider_timestamp=timestamp,
                content=content,
            ),
            content=content,
            provider_timestamp=timestamp,
            canonical_url=comment_url,
            parent_context=parent,
            author_handle=optional_text(item, "uniqueId", "username")
            or nested_text(item, "user", "uniqueId", "nickname"),
            observed_public_metrics=observed_metrics(
                item, {"likes": ("diggCount", "likes"), "replies": ("replyCount",)}
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
            if parent is None:
                raise ParserError("TikTok comment parsing requires its associated parent context")
            return self.parse_comment(item, parent=parent)
        return self.parse_video(item)
