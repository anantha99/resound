"""Twitter / X source.

Uses tweepy with bearer token auth (app-only). Calls the recent_search
endpoint, which returns tweets from the last 7 days matching a query.

CAVEATS:
  - Twitter's free tier is essentially unusable for production polling
    (~100 reads/month at last check). The Basic tier ($100/mo) gets ~10k
    tweets/month, which is enough for most brand monitoring.
  - If TWITTER_BEARER_TOKEN is not set, the adapter returns no signals and
    logs an informational message — does not crash the pipeline.
  - We use recent_search rather than streaming because polling fits the
    Resound architecture better and avoids needing a long-running connection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from resound.config import env
from resound.core.source import SourceAdapter
from resound.models import RawSignal

logger = logging.getLogger(__name__)


class TwitterSource(SourceAdapter):
    """Polls Twitter / X for brand mentions.

    params (sources.yaml):
      handles: list of @handles to monitor (e.g., ['@fulfilio'])
      search_terms: list of keywords / hashtags
      limit: max tweets per query per poll (default 50, max 100 per request)
      include_retweets: whether to include retweets (default False)
    """

    name = "twitter"

    def __init__(self, brand_slug: str, params: dict):
        super().__init__(brand_slug, params)
        self.handles = params.get("handles", [])
        self.search_terms = params.get("search_terms", [])
        self.limit = min(int(params.get("limit", 50)), 100)  # API max per request
        self.include_retweets = bool(params.get("include_retweets", False))
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        bearer = env("TWITTER_BEARER_TOKEN")
        if not bearer:
            logger.info(
                "TwitterSource: TWITTER_BEARER_TOKEN not set; skipping. "
                "Set it in .env to enable Twitter ingestion."
            )
            return None

        try:
            import tweepy
        except ImportError as exc:
            raise RuntimeError(
                "tweepy not installed. Run: pip install tweepy"
            ) from exc

        self._client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=False)
        return self._client

    def poll(self) -> Iterable[RawSignal]:
        client = self._get_client()
        if client is None:
            return

        # Build queries: handles get an "@handle OR (to:handle) OR (from:handle)"
        # treatment; search_terms are passed through as-is.
        queries: list[tuple[str, str]] = []
        for handle in self.handles:
            h = handle.lstrip("@")
            queries.append((handle, f"(@{h} OR to:{h} OR from:{h})"))
        for term in self.search_terms:
            queries.append((term, term))

        if not queries:
            logger.warning(
                "TwitterSource: no handles or search_terms configured for %s",
                self.brand_slug,
            )
            return

        for label, q in queries:
            if not self.include_retweets:
                q = f"{q} -is:retweet"

            try:
                resp = client.search_recent_tweets(
                    query=q,
                    max_results=self.limit,
                    tweet_fields=["created_at", "author_id", "public_metrics", "lang"],
                    expansions=["author_id"],
                    user_fields=["username", "name"],
                )
            except Exception as exc:
                logger.warning("Twitter search failed for query %r: %s", q, exc)
                continue

            tweets = resp.data or []
            users_by_id = {u.id: u for u in (resp.includes or {}).get("users", [])}

            for tweet in tweets:
                # English-only filter for v1.
                if getattr(tweet, "lang", None) and tweet.lang != "en":
                    continue

                author = users_by_id.get(tweet.author_id)
                author_handle = f"@{author.username}" if author else None

                metrics = getattr(tweet, "public_metrics", {}) or {}
                reach = (
                    metrics.get("retweet_count", 0)
                    + metrics.get("like_count", 0)
                    + metrics.get("reply_count", 0)
                )

                created = tweet.created_at or datetime.now(tz=timezone.utc)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)

                yield RawSignal(
                    source="twitter",
                    external_id=str(tweet.id),
                    url=f"https://twitter.com/i/web/status/{tweet.id}",
                    author_handle=author_handle,
                    content=tweet.text,
                    posted_at=created,
                    raw_metadata={
                        "query_label": label,
                        "metrics": dict(metrics),
                        "reach": reach,
                        "lang": getattr(tweet, "lang", None),
                    },
                )
