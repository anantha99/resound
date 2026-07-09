"""Public-listening source provider contracts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal

from resound.models import RawSignal

SourceType = Literal["instagram_public", "reddit", "tiktok", "x_public", "youtube_comments"]

V1_PUBLIC_SOURCE_TYPES: set[SourceType] = {
    "instagram_public",
    "reddit",
    "tiktok",
    "x_public",
    "youtube_comments",
}

APIFY_ACTORS: dict[SourceType, str] = {
    "instagram_public": "apify/instagram-scraper",
    "reddit": "solidcode/reddit-scraper",
    "tiktok": "clockworks/tiktok-scraper",
    "x_public": "apidojo/twitter-scraper-lite",
    "youtube_comments": "streamers/youtube-scraper",
}

SOURCE_NAMES: dict[str, str] = {
    "instagram_public": "instagram",
    "reddit": "reddit",
    "tiktok": "tiktok",
    "x_public": "x",
    "youtube_comments": "youtube",
}


@dataclass(frozen=True)
class ListeningProfile:
    brand_slug: str
    brand_names: list[str] = field(default_factory=list)
    product_names: list[str] = field(default_factory=list)
    competitor_names: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    excluded_terms: list[str] = field(default_factory=list)
    enabled_sources: list[SourceType] = field(
        default_factory=lambda: sorted(V1_PUBLIC_SOURCE_TYPES),
    )
    cadence_minutes: int = 15
    locale: str | None = None
    language: str = "en"
    setup_notes: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class ListeningProfileSuggestion:
    suggestion_type: str
    value: str
    reason: str | None = None
    status: Literal["pending", "accepted", "edited", "rejected"] = "pending"


@dataclass(frozen=True)
class ListeningProfileRevision:
    field_name: str
    old_value: Any
    new_value: Any
    authored_by: Literal["user", "agent"]


@dataclass(frozen=True)
class ApifyQueryConfig:
    source_type: SourceType
    actor_id: str
    query_terms: list[str]
    excluded_terms: list[str]
    cadence_minutes: int
    locale: str | None
    language: str


CONTENT_KEYS_BY_SOURCE: dict[str, tuple[str, ...]] = {
    "instagram_public": ("caption", "text", "body", "commentText", "title", "description"),
    "tiktok": ("text", "description", "desc", "title"),
    "x_public": ("text", "fullText", "body", "title", "description"),
    "youtube_comments": ("comment", "text", "description", "title"),
}

URL_KEYS = (
    "url",
    "link",
    "permalink",
    "webVideoUrl",
    "twitterUrl",
    "pageUrl",
    "commentUrl",
    "postUrl",
)

DATETIME_KEYS = (
    "createdAt",
    "created_at",
    "postedAt",
    "timestamp",
    "date",
    "createTimeISO",
    "publishedAt",
    "publishedTime",
    "createTime",
)

EXTERNAL_ID_KEYS = (
    "fullId",
    "cid",
    "id",
    "externalId",
    "external_id",
    "shortCode",
    "tweetId",
    "videoId",
)

AUTHOR_KEYS = (
    "author.userName",
    "author.username",
    "author.name",
    "authorMeta.name",
    "authorMeta.nickName",
    "ownerUsername",
    "authorUsername",
    "username",
    "channelName",
    "ownerFullName",
    "author",
)


def build_apify_query_configs(profile: ListeningProfile) -> list[ApifyQueryConfig]:
    query_terms = sorted(
        {
            term.strip()
            for term in [
                *profile.brand_names,
                *profile.product_names,
                *profile.competitor_names,
                *profile.keywords,
            ]
            if term and term.strip()
        }
    )
    excluded_terms = sorted({term.strip() for term in profile.excluded_terms if term.strip()})
    enabled_sources = sorted(set(profile.enabled_sources).intersection(V1_PUBLIC_SOURCE_TYPES))
    return [
        ApifyQueryConfig(
            source_type=source_type,
            actor_id=APIFY_ACTORS[source_type],
            query_terms=query_terms,
            excluded_terms=excluded_terms,
            cadence_minutes=profile.cadence_minutes,
            locale=profile.locale,
            language=profile.language,
        )
        for source_type in enabled_sources
    ]


def normalize_apify_item(
    *,
    source_type: str,
    item: dict[str, Any],
    actor_id: str,
    run_id: str | None,
) -> RawSignal:
    if source_type not in SOURCE_NAMES:
        raise ValueError(f"Unsupported Apify public source type: {source_type}")

    content = _content_for_source(source_type, item)
    if not content:
        raise ValueError("Apify item is missing text content")

    url = _first_text(item, *URL_KEYS)
    posted_at = _parse_datetime(_first_text(item, *DATETIME_KEYS))
    external_id = _first_text(item, *EXTERNAL_ID_KEYS)
    if not external_id:
        hash_input = f"{source_type}:{url}:{content}:{posted_at.isoformat()}"
        external_id = hashlib.sha256(hash_input.encode()).hexdigest()

    author = _first_text(item, *AUTHOR_KEYS)
    metadata = {
        key: value
        for key, value in item.items()
        if key not in {"text", "body", "commentText", "caption", "description"}
    }
    metadata.update(
        {
            "provider": "apify",
            "provider_actor_id": actor_id,
            "provider_run_id": run_id,
            "source_type": source_type,
        }
    )

    return RawSignal(
        source=SOURCE_NAMES[source_type],
        source_mode="public_listening",
        provider="apify",
        external_id=str(external_id),
        url=url,
        author_handle=author,
        content=content,
        posted_at=posted_at,
        raw_metadata=metadata,
    )


def _first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _value_for_key(item, key)
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _value_for_key(item: dict[str, Any], key: str) -> Any:
    if key in item:
        return item[key]
    value: Any = item
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
        if value is None:
            return None
    return value


def _content_for_source(source_type: str, item: dict[str, Any]) -> str | None:
    if source_type == "reddit":
        return _reddit_content(item)
    if source_type == "youtube_comments":
        return _youtube_content(item)
    return _first_text(
        item,
        *CONTENT_KEYS_BY_SOURCE.get(source_type, ("text", "body", "title", "description")),
    )


def _reddit_content(item: dict[str, Any]) -> str | None:
    title = _first_text(item, "title", "postTitle")
    body = _first_text(item, "text", "body", "selftext", "commentText")
    if title and body and title != body:
        return f"{title}\n\n{body}"
    return title or body


def _youtube_content(item: dict[str, Any]) -> str | None:
    comment = _first_text(item, "comment", "commentText", "body")
    title = _first_text(item, "title", "videoTitle")
    if comment:
        return f"{title}\n\n{comment}" if title and title != comment else comment
    description = _first_text(item, "text", "description")
    if title and description and title != description:
        return f"{title}\n\n{description}"
    return description or title


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=UTC)
    normalized = value.replace("Z", "+00:00")
    try:
        timestamp = float(normalized)
    except ValueError:
        timestamp = None
    if timestamp is not None:
        if timestamp > 1_000_000_000_000:
            timestamp = timestamp / 1000
        return datetime.fromtimestamp(timestamp, tz=UTC)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return datetime.now(tz=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
