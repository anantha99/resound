from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from resound.social.apify_adapters import AdapterBlockedError, ParserError, execute_actor_run
from resound.social.apify_adapters.instagram import (
    InstagramAdapter,
    InstagramMentionSelector,
)
from resound.social.apify_adapters.reddit import RedditAdapter
from resound.social.apify_adapters.tiktok import TikTokAdapter
from resound.social.apify_adapters.x import XAdapter
from resound.social.apify_adapters.youtube import YouTubeAdapter
from resound.social.common import ProviderBudget
from resound.social.contracts import SourcePath
from resound.social.registry import ACTOR_REGISTRY, get_source_adapter


def test_reddit_and_x_exact_build_inputs_are_serializable_but_execution_is_blocked() -> None:
    reddit = RedditAdapter.serialize_input(
        subreddits=["acme"],
        searches=["Acme"],
        start_urls=["https://www.reddit.com/r/acme/new/"],
        max_items=7,
    )
    x_payload = XAdapter.serialize_input(
        twitter_handles=["acme"],
        search_terms=["Acme"],
        start_urls=["https://x.com/acme"],
        max_items=7,
    )
    assert reddit["subreddits"] == ["acme"]
    assert reddit["searches"] == ["Acme"]
    assert reddit["startUrls"] == ["https://www.reddit.com/r/acme/new/"]
    assert x_payload["twitterHandles"] == ["acme"]
    assert x_payload["searchTerms"] == ["Acme"]
    assert x_payload["startUrls"] == ["https://x.com/acme"]
    assert ACTOR_REGISTRY["reddit_discovery"].build_number == "1.1.31"
    assert ACTOR_REGISTRY["reddit_discovery"].build_id == "LxJ3Vm9RHSEJcQEYK"
    assert ACTOR_REGISTRY["x_discovery"].build_number == "0.0.935"
    assert ACTOR_REGISTRY["x_discovery"].build_id == "NqWYV0k5wlJ9R5bi6"
    with pytest.raises(AdapterBlockedError, match="fixtures.*canary"):
        RedditAdapter().plan(path=SourcePath.MENTION_DISCOVERY, searches=["Acme"], max_items=1)
    with pytest.raises(AdapterBlockedError, match="fixtures.*canary"):
        XAdapter().plan(path=SourcePath.MENTION_DISCOVERY, search_terms=["Acme"], max_items=1)


def test_youtube_uses_request_objects_and_search_queries_with_video_only_fields() -> None:
    adapter = YouTubeAdapter()
    official = adapter.plan_official(channel_urls=["https://www.youtube.com/@acme"], max_items=5)[0]
    mention = adapter.plan_mentions(search_queries=["Acme review"], max_items=6)[0]
    assert official.actor_input["startUrls"] == [{"url": "https://www.youtube.com/@acme"}]
    assert "searchQueries" not in official.actor_input
    assert mention.actor_input["searchQueries"] == ["Acme review"]
    assert "startUrls" not in mention.actor_input
    assert official.path == SourcePath.OFFICIAL_DISCOVERY
    assert mention.path == SourcePath.MENTION_DISCOVERY
    assert len((official, mention)) == adapter.max_runs == 2
    assert all(
        token not in key.lower()
        for plan in (official, mention)
        for key in plan.actor_input
        for token in ("comment", "subtitle", "transcript", "download", "ai")
    )


def test_instagram_exact_nine_run_bound_and_item_multiplication() -> None:
    adapter = InstagramAdapter()
    official = adapter.plan_official(
        direct_urls=["https://instagram.com/acme", "https://instagram.com/acme2"],
        item_cap=25,
    )
    mentions = adapter.plan_mentions(
        selectors=[InstagramMentionSelector(f"tag-{index}") for index in range(6)],
        item_cap=25,
    )
    official_comments = adapter.plan_comments(
        path=SourcePath.OFFICIAL_COMMENTS,
        parent_urls=["https://instagram.com/p/1", "https://instagram.com/p/2"],
        path_comment_cap=25,
        max_comments_per_parent=5,
    )
    mention_comments = adapter.plan_comments(
        path=SourcePath.MENTION_COMMENTS,
        parent_urls=["https://instagram.com/p/3"],
        path_comment_cap=25,
        max_comments_per_parent=5,
    )
    plans = official + mentions + official_comments + mention_comments
    assert len(plans) == adapter.worst_case_runs == 9
    assert official[0].actor_input["directUrls"] == [
        "https://instagram.com/acme",
        "https://instagram.com/acme2",
    ]
    assert official[0].actor_input["resultsLimit"] == 12
    assert official[0].requested_row_maximum == 24
    assert [plan.actor_input["searchLimit"] for plan in mentions] == [1] * 6
    assert [plan.actor_input["resultsLimit"] for plan in mentions] == [4] * 6
    assert official_comments[0].actor_input == {
        "directUrls": ["https://instagram.com/p/1", "https://instagram.com/p/2"],
        "resultsLimit": 5,
        "includeNestedComments": False,
    }
    adapter.validate_run_count(plans, max_runs=9)
    with pytest.raises(ValueError, match="Run count"):
        adapter.validate_run_count(plans, max_runs=8)


def test_instagram_rejects_unsupported_or_unallocatable_selectors() -> None:
    with pytest.raises(ValueError, match="only hashtag"):
        InstagramMentionSelector("arbitrary caption phrase", "keyword")
    with pytest.raises(ValueError, match="cannot allocate"):
        InstagramAdapter().plan_mentions(
            selectors=[InstagramMentionSelector("one"), InstagramMentionSelector("two")],
            item_cap=1,
        )


def test_tiktok_dispatch_multiplies_rows_and_uses_two_actor_runs_only() -> None:
    adapter = TikTokAdapter()
    official = adapter.plan_official(
        profiles=["acme", "acme-help"], item_cap=25, comments_per_post=5
    )
    mentions = adapter.plan_mentions(
        hashtags=["acme", "acmereview"],
        search_queries=["Acme review"],
        item_cap=25,
        comments_per_post=5,
    )
    assert len(official + mentions) == adapter.max_runs == 2
    assert official[0].actor_input["profiles"] == ["acme", "acme-help"]
    assert official[0].actor_input["resultsPerPage"] == 12
    assert official[0].requested_row_maximum == 24
    assert mentions[0].actor_input["hashtags"] == ["acme", "acmereview"]
    assert mentions[0].actor_input["searchQueries"] == ["Acme review"]
    assert mentions[0].actor_input["resultsPerPage"] == 8
    assert mentions[0].requested_row_maximum == 24
    assert mentions[0].minimum_call_charge_usd == Decimal("0.50")
    forbidden = ("download", "media", "subtitle", "transcript", "ai")
    assert all(token not in key.lower() for key in mentions[0].actor_input for token in forbidden)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v2/datasets/comments/items",
        "http://api.apify.com/v2/datasets/comments/items",
        "https://api.apify.com/v2/datasets/comments/not-items",
        "https://api.apify.com/v2/datasets/comments/items/extra",
        "https://api.apify.com/v2/datasets/bad%2Fid/items",
    ],
)
def test_tiktok_rejects_mutated_comment_dataset_urls(url: str) -> None:
    with pytest.raises(ParserError):
        TikTokAdapter.comments_dataset_reference(url)


def test_tiktok_fetches_exact_dataset_id_with_authenticated_client_contract() -> None:
    calls: list[dict[str, object]] = []

    class Client:
        def fetch_dataset_items(self, dataset_id: str, **kwargs):
            calls.append({"dataset_id": dataset_id, **kwargs})
            return [{"id": "synthetic-comment"}]

    items = TikTokAdapter.fetch_comments(
        Client(),
        comments_dataset_url=(
            "https://api.apify.com/v2/datasets/comments-1/items?token=provider-redacted"
        ),
        limit=5,
        page_size=2,
    )
    assert items == [{"id": "synthetic-comment"}]
    assert calls == [
        {
            "dataset_id": "comments-1",
            "dataset_url": "https://api.apify.com/v2/datasets/comments-1/items",
            "limit": 5,
            "page_size": 2,
        }
    ]


def test_synthetic_parsers_enforce_exact_time_content_identity_and_parent_topology() -> None:
    fixture = json.loads(
        Path("tests/fixtures/apify/synthetic/parser_rows.json").read_text(encoding="utf-8")
    )
    assert fixture["synthetic_only"] is True
    instagram = InstagramAdapter.parse_comment(fixture["instagram_comment"])
    tiktok = TikTokAdapter.parse_video(fixture["tiktok_video"])
    youtube = YouTubeAdapter.parse(fixture["youtube_video"])
    assert instagram.canonical_url == fixture["instagram_comment"]["commentUrl"]
    assert instagram.parent_url == fixture["instagram_comment"]["postUrl"]
    assert tiktok.content_kind == "video"
    assert youtube.content_kind == "video"
    assert instagram.provider_timestamp == datetime(2026, 7, 17, 1, 2, 3, tzinfo=UTC)

    mutation = deepcopy(fixture["instagram_comment"])
    mutation["timestamp"] = "2 hours ago"
    with pytest.raises(ParserError, match="relative"):
        InstagramAdapter.parse_comment(mutation)
    mutation = deepcopy(fixture["instagram_comment"])
    mutation.pop("commentUrl")
    with pytest.raises(ParserError, match="commentUrl"):
        InstagramAdapter.parse_comment(mutation)
    mutation = deepcopy(fixture["youtube_video"])
    mutation.pop("title")
    with pytest.raises(ParserError, match="content"):
        YouTubeAdapter.parse(mutation)


def test_parser_duplicate_rows_produce_the_same_native_identity() -> None:
    row = {
        "id": "same-provider-id",
        "text": "Synthetic post",
        "createdAt": "2026-07-17T01:02:03Z",
        "url": "https://x.com/synthetic/status/1",
    }
    assert XAdapter.parse(row).identity == XAdapter.parse(deepcopy(row)).identity


def test_each_run_gets_remaining_hard_charge_cap_and_preserves_path_attribution() -> None:
    plan = YouTubeAdapter().plan_mentions(search_queries=["Acme"], max_items=2)[0]
    calls: list[tuple[str, object]] = []

    class Client:
        def run_actor(self, actor_id: str, actor_input: dict[str, object], **kwargs):
            calls.append(("charge", kwargs["max_total_charge_usd"]))
            calls.append(("build", kwargs["build_number"]))
            kwargs["reservation_callback"]()
            return {"id": "run-1"}

        def wait_for_run(self, run):
            return {
                **run,
                "status": "SUCCEEDED",
                "usageTotalUsd": "0.25",
                "defaultDatasetId": "dataset-1",
            }

        def fetch_dataset_items(self, dataset_id: str, **kwargs):
            calls.append(("limit", kwargs["limit"]))
            return [{"id": "one"}]

    budget = ProviderBudget(
        ceiling_usd=Decimal("1.00"),
        charge_quantum_usd=Decimal("0.01"),
        minimum_call_charge_usd=Decimal("0.01"),
        conservative_request_cost_usd=Decimal("0.01"),
    )
    result = execute_actor_run(
        Client(), plan=plan, budget=budget, reservation_id="mention-1", page_size=10
    )
    assert calls == [("charge", Decimal("1.00")), ("build", "0.0.273"), ("limit", 2)]
    assert result.path == SourcePath.MENTION_DISCOVERY
    assert result.usage_total_usd == Decimal("0.25")
    assert budget.reconciled_spend_usd == Decimal("0.25")


def test_tiktok_minimum_blocks_call_below_fifty_cents() -> None:
    plan = TikTokAdapter().plan_official(profiles=["acme"], item_cap=1, comments_per_post=1)[0]
    budget = ProviderBudget(
        ceiling_usd=Decimal("0.49"),
        charge_quantum_usd=Decimal("0.01"),
        minimum_call_charge_usd=Decimal("0.01"),
        conservative_request_cost_usd=Decimal("0.01"),
    )
    with pytest.raises(RuntimeError, match="actor call minimum"):
        execute_actor_run(
            object(), plan=plan, budget=budget, reservation_id="blocked", page_size=10
        )


def test_registry_exposes_every_actor_specific_adapter() -> None:
    assert isinstance(get_source_adapter("reddit"), RedditAdapter)
    assert isinstance(get_source_adapter("instagram"), InstagramAdapter)
    assert isinstance(get_source_adapter("tiktok"), TikTokAdapter)
    assert isinstance(get_source_adapter("x"), XAdapter)
    assert isinstance(get_source_adapter("youtube"), YouTubeAdapter)
