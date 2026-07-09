from __future__ import annotations

from datetime import UTC, datetime

import pytest

from resound.social import (
    V1_PUBLIC_SOURCE_TYPES,
    ListeningProfile,
    build_apify_query_configs,
    normalize_apify_item,
)
from resound.social.apify import apify_actor_input, apify_actor_path_id


def test_apify_public_payload_normalizes_to_raw_signal_with_provider_metadata():
    raw = normalize_apify_item(
        source_type="reddit",
        item={
            "id": "abc123",
            "text": "Shipping damage keeps happening.",
            "url": "https://reddit.com/r/acme/comments/abc123",
            "author": "u/example",
            "createdAt": "2026-06-30T12:00:00Z",
            "score": 42,
        },
        actor_id="apify/reddit-scraper",
        run_id="run-1",
    )

    assert raw.source == "reddit"
    assert raw.source_mode == "public_listening"
    assert raw.provider == "apify"
    assert raw.external_id == "abc123"
    assert raw.content == "Shipping damage keeps happening."
    assert raw.raw_metadata["provider"] == "apify"
    assert raw.raw_metadata["provider_run_id"] == "run-1"
    assert raw.raw_metadata["source_type"] == "reddit"
    assert raw.raw_metadata["score"] == 42


def test_listening_profile_produces_deterministic_v1_apify_configs():
    profile = ListeningProfile(
        brand_slug="acme",
        brand_names=["Acme"],
        product_names=["Rocket Skates"],
        competitor_names=["Globex"],
        keywords=["shipping damage", "late delivery"],
        excluded_terms=["jobs"],
        enabled_sources=list(V1_PUBLIC_SOURCE_TYPES),
        cadence_minutes=15,
        locale="en-US",
    )

    configs = build_apify_query_configs(profile)

    assert [config.source_type for config in configs] == sorted(V1_PUBLIC_SOURCE_TYPES)
    assert configs[0].query_terms == [
        "Acme",
        "Globex",
        "Rocket Skates",
        "late delivery",
        "shipping damage",
    ]
    assert all(config.cadence_minutes == 15 for config in configs)
    assert all(config.excluded_terms == ["jobs"] for config in configs)


def test_reddit_apify_input_uses_actor_schema_and_item_cap():
    profile = ListeningProfile(
        brand_slug="acme",
        keywords=["Acme", "shipping damage"],
        enabled_sources=["reddit"],
    )

    config = build_apify_query_configs(profile)[0]
    payload = apify_actor_input(config, max_items=7)

    assert config.actor_id == "solidcode/reddit-scraper"
    assert apify_actor_path_id(config.actor_id) == "solidcode~reddit-scraper"
    assert payload["searches"] == ["Acme", "shipping damage"]
    assert payload["subreddits"] == []
    assert payload["searchPosts"] is True
    assert payload["skipComments"] is True
    assert payload["maxItems"] == 7


def test_non_reddit_apify_inputs_use_channel_actor_schemas():
    profile = ListeningProfile(
        brand_slug="acme",
        keywords=["Acme"],
        excluded_terms=["jobs"],
        enabled_sources=["instagram_public", "tiktok", "x_public", "youtube_comments"],
        language="en",
    )

    payloads = {
        config.source_type: apify_actor_input(config, max_items=7)
        for config in build_apify_query_configs(profile)
    }

    assert payloads["instagram_public"] == {
        "resultsType": "posts",
        "directUrls": [],
        "search": "Acme",
        "searchType": "user",
        "searchLimit": 1,
        "resultsLimit": 7,
        "onlyPostsNewerThan": "1 month",
        "addParentData": True,
    }
    assert payloads["tiktok"]["searchQueries"] == ["Acme"]
    assert payloads["tiktok"]["resultsPerPage"] == 7
    assert payloads["tiktok"]["searchSection"] == "/video"
    assert payloads["tiktok"]["shouldDownloadVideos"] is False
    assert payloads["x_public"]["searchTerms"] == ["Acme -jobs lang:en"]
    assert payloads["x_public"]["sort"] == "Latest"
    assert payloads["x_public"]["maxItems"] == 7
    assert payloads["youtube_comments"]["searchQueries"] == ["Acme"]
    assert payloads["youtube_comments"]["maxResults"] == 7
    assert payloads["youtube_comments"]["sortingOrder"] == "date"


@pytest.mark.parametrize(
    ("source_type", "item", "expected_source", "expected_author", "expected_content"),
    [
        (
            "instagram_public",
            {
                "id": "ig-1",
                "caption": "Acme unboxing looked great.",
                "ownerUsername": "creator",
                "timestamp": "2026-06-30T12:00:00Z",
                "url": "https://www.instagram.com/p/ig-1/",
            },
            "instagram",
            "creator",
            "Acme unboxing looked great.",
        ),
        (
            "tiktok",
            {
                "id": "tt-1",
                "text": "Acme delivery review",
                "authorMeta": {"name": "reviewer"},
                "createTimeISO": "2026-06-30T12:00:00Z",
                "webVideoUrl": "https://www.tiktok.com/@reviewer/video/tt-1",
            },
            "tiktok",
            "reviewer",
            "Acme delivery review",
        ),
        (
            "x_public",
            {
                "id": "tweet-1",
                "text": "Acme checkout is down again.",
                "author": {"userName": "buyer"},
                "createdAt": "Fri Nov 24 17:49:36 +0000 2023",
                "url": "https://x.com/buyer/status/tweet-1",
            },
            "x",
            "buyer",
            "Acme checkout is down again.",
        ),
        (
            "youtube_comments",
            {
                "id": "yt-1",
                "title": "Acme review",
                "text": "The checkout flow failed during the demo.",
                "channelName": "Reviewer Channel",
                "url": "https://www.youtube.com/watch?v=yt-1",
                "date": "2026-06-30T12:00:00Z",
            },
            "youtube",
            "Reviewer Channel",
            "Acme review\n\nThe checkout flow failed during the demo.",
        ),
    ],
)
def test_v1_social_actor_payloads_normalize_to_raw_signals(
    source_type,
    item,
    expected_source,
    expected_author,
    expected_content,
):
    raw = normalize_apify_item(
        source_type=source_type,
        item=item,
        actor_id="apify/test-actor",
        run_id="run-1",
    )

    assert raw.source == expected_source
    assert raw.author_handle == expected_author
    assert raw.content == expected_content
    assert raw.provider == "apify"
    assert raw.raw_metadata["source_type"] == source_type


def test_youtube_comment_payload_preserves_comment_context():
    raw = normalize_apify_item(
        source_type="youtube_comments",
        item={
            "cid": "comment-1",
            "comment": "Acme support fixed this fast.",
            "author": "@buyer",
            "pageUrl": "https://www.youtube.com/watch?v=yt-1",
            "title": "Acme launch review",
        },
        actor_id="streamers/youtube-comments-scraper",
        run_id="run-1",
    )

    assert raw.external_id == "comment-1"
    assert raw.source == "youtube"
    assert raw.author_handle == "@buyer"
    assert raw.content == "Acme launch review\n\nAcme support fixed this fast."


def test_missing_optional_payload_fields_still_creates_valid_signal():
    raw = normalize_apify_item(
        source_type="x_public",
        item={"text": "Acme launch reaction", "createdAt": datetime.now(tz=UTC).isoformat()},
        actor_id="apify/x-scraper",
        run_id=None,
    )

    assert raw.external_id
    assert raw.author_handle is None
    assert raw.url is None
    assert raw.source == "x"
