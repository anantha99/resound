"""Canonical public-source registry shared by resolver and future adapters."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from resound.social.contracts import PublicSource


@dataclass(frozen=True)
class SourceRegistration:
    source: PublicSource
    storage_platform: str
    config_aliases: tuple[str, ...]
    blocked_by_default: bool = False


@dataclass(frozen=True)
class ActorRegistration:
    actor_id: str
    build_id: str
    build_number: str
    input_schema_sha256: str | None = None
    input_schema_sha256_prefix: str | None = None
    output_schema_sha256_prefix: str | None = None
    has_formal_output_schema: bool = False
    canary_required: bool = False
    url_shape: str = "none"
    minimum_call_charge_usd: Decimal | None = None


SOURCE_REGISTRY = {
    "reddit": SourceRegistration(PublicSource.REDDIT, "reddit", ("reddit",), True),
    "instagram": SourceRegistration(
        PublicSource.INSTAGRAM, "instagram", ("instagram", "instagram_public")
    ),
    "tiktok": SourceRegistration(PublicSource.TIKTOK, "tiktok", ("tiktok",)),
    "x": SourceRegistration(PublicSource.X, "x", ("x", "x_public", "twitter"), True),
    "youtube": SourceRegistration(
        PublicSource.YOUTUBE, "youtube", ("youtube", "youtube_comments")
    ),
}


ACTOR_REGISTRY = {
    "reddit_discovery": ActorRegistration(
        actor_id="solidcode/reddit-scraper",
        build_id="LxJ3Vm9RHSEJcQEYK",
        build_number="1.1.31",
        input_schema_sha256=(
            "58ea3036200e494ef3e8405b8de3db9fe8b47abab4c3216e8d460c95ff33ddca"
        ),
        canary_required=True,
        url_shape="list[str]",
    ),
    "instagram_discovery": ActorRegistration(
        actor_id="apify/instagram-scraper",
        build_id="AnGYqGQjcKAa1VSUK",
        build_number="0.0.690",
        input_schema_sha256_prefix="599b69bc",
        output_schema_sha256_prefix="20edc518",
        has_formal_output_schema=True,
        url_shape="list[str]",
    ),
    "instagram_comments": ActorRegistration(
        actor_id="apify/instagram-comment-scraper",
        build_id="QnsnqzHndqNZTLqWw",
        build_number="0.0.511",
        input_schema_sha256_prefix="4b34f7eb",
        output_schema_sha256_prefix="2b07394d",
        has_formal_output_schema=True,
        url_shape="list[str]",
    ),
    "tiktok": ActorRegistration(
        actor_id="clockworks/tiktok-scraper",
        build_id="JYyRr8f5BczSjcmPO",
        build_number="0.0.561",
        input_schema_sha256_prefix="3c657f7b",
        output_schema_sha256_prefix="84ba0128",
        has_formal_output_schema=True,
        minimum_call_charge_usd=Decimal("0.50"),
    ),
    "x_discovery": ActorRegistration(
        actor_id="apidojo/twitter-scraper-lite",
        build_id="NqWYV0k5wlJ9R5bi6",
        build_number="0.0.935",
        input_schema_sha256_prefix="f0138656",
        canary_required=True,
        url_shape="list[str]",
    ),
    "youtube_discovery": ActorRegistration(
        actor_id="streamers/youtube-scraper",
        build_id="N0ksZ5khxS6TcgW8s",
        build_number="0.0.273",
        input_schema_sha256_prefix="3db1abc9",
        output_schema_sha256_prefix="5e47e195",
        has_formal_output_schema=True,
        url_shape="list[request_object]",
    ),
}

