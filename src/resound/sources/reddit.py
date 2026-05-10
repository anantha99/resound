"""Reddit source.

Pulls from configured subreddits and brand-name search. Each item becomes a
RawSignal with source='reddit'. Two backends are supported, selected by the
REDDIT_BACKEND env var:

  - "composio" (default): routes through Composio's managed Reddit OAuth app.
    Requires COMPOSIO_API_KEY and COMPOSIO_USER_ID. Avoids Reddit's
    Responsible Builder Policy (Nov 2025) approval gate for new credentials.
  - "praw": direct Reddit API via PRAW. Requires REDDIT_CLIENT_ID/SECRET
    issued by reddit.com/prefs/apps.

Both backends emit identical RawSignal shapes so downstream code is
backend-agnostic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

from resound.config import env
from resound.core.source import SourceAdapter
from resound.models import RawSignal

logger = logging.getLogger(__name__)


class RedditSource(SourceAdapter):
    """Polls Reddit for brand mentions.

    params (from sources.yaml):
      subreddits: list of subreddit names to scan
      search_terms: list of search queries to run across reddit
      limit: max items to fetch per subreddit/term per poll (default 25)
      include_comments: whether to fetch top comments on matched posts (default True)
    """

    name = "reddit"

    def __init__(self, brand_slug: str, params: dict):
        super().__init__(brand_slug, params)
        self._backend: _Backend | None = None

    def _get_backend(self) -> "_Backend":
        if self._backend is not None:
            return self._backend
        choice = (env("REDDIT_BACKEND") or "composio").strip().lower()
        if choice == "praw":
            self._backend = _PrawBackend(self.brand_slug)
        elif choice == "composio":
            self._backend = _ComposioBackend()
        else:
            raise RuntimeError(
                f"Unknown REDDIT_BACKEND={choice!r}. Use 'composio' or 'praw'."
            )
        return self._backend

    def poll(self) -> Iterable[RawSignal]:
        backend = self._get_backend()
        limit = int(self.params.get("limit", 25))

        for sub_name in self.params.get("subreddits", []):
            try:
                for post in backend.fetch_subreddit(sub_name, limit):
                    yield self._post_to_signal(post, channel=f"r/{sub_name}")
            except Exception as exc:
                logger.warning(f"Reddit subreddit {sub_name!r} poll failed: {exc}")

        for term in self.params.get("search_terms", []):
            try:
                for post in backend.fetch_search(term, limit):
                    yield self._post_to_signal(post, channel=f"search:{term}")
            except Exception as exc:
                logger.warning(f"Reddit search {term!r} failed: {exc}")

    @staticmethod
    def _post_to_signal(post: dict[str, Any], channel: str) -> RawSignal:
        body = post.get("selftext") or ""
        title = post.get("title") or ""
        content = f"{title}\n\n{body}" if body else title
        permalink = post.get("permalink") or ""
        url = f"https://reddit.com{permalink}" if permalink.startswith("/") else permalink
        return RawSignal(
            source="reddit",
            external_id=str(post["id"]),
            url=url,
            author_handle=str(post["author"]) if post.get("author") else None,
            content=content,
            posted_at=datetime.fromtimestamp(float(post["created_utc"]), tz=timezone.utc),
            raw_metadata={
                "channel": channel,
                "subreddit": str(post.get("subreddit") or ""),
                "score": post.get("score"),
                "num_comments": post.get("num_comments"),
                "upvote_ratio": post.get("upvote_ratio"),
            },
        )


# ---------------------------------------------------------------------------
# Backends
#
# Each backend exposes the same shape:
#   fetch_subreddit(name: str, limit: int) -> Iterable[dict]
#   fetch_search(term: str, limit: int) -> Iterable[dict]
#
# The dict keys consumed by RedditSource._post_to_signal are:
#   id, permalink, author, title, selftext, created_utc, score,
#   num_comments, upvote_ratio, subreddit
# ---------------------------------------------------------------------------


class _Backend:
    def fetch_subreddit(self, name: str, limit: int) -> Iterable[dict[str, Any]]:
        raise NotImplementedError

    def fetch_search(self, term: str, limit: int) -> Iterable[dict[str, Any]]:
        raise NotImplementedError


class _PrawBackend(_Backend):
    def __init__(self, brand_slug: str):
        self._brand_slug = brand_slug
        self._reddit = None

    def _client(self):
        if self._reddit is not None:
            return self._reddit
        try:
            import praw
        except ImportError as exc:
            raise RuntimeError("praw not installed; run pip install praw") from exc

        client_id = env("REDDIT_CLIENT_ID")
        client_secret = env("REDDIT_CLIENT_SECRET")
        user_agent = env("REDDIT_USER_AGENT") or f"resound:v0.1.0 ({self._brand_slug})"

        if not client_id or not client_secret:
            raise RuntimeError(
                "Reddit credentials missing. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env."
            )

        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        self._reddit.read_only = True
        return self._reddit

    def fetch_subreddit(self, name: str, limit: int) -> Iterable[dict[str, Any]]:
        reddit = self._client()
        for submission in reddit.subreddit(name).new(limit=limit):
            yield self._submission_to_dict(submission)

    def fetch_search(self, term: str, limit: int) -> Iterable[dict[str, Any]]:
        reddit = self._client()
        for submission in reddit.subreddit("all").search(term, sort="new", limit=limit):
            yield self._submission_to_dict(submission)

    @staticmethod
    def _submission_to_dict(submission) -> dict[str, Any]:
        return {
            "id": submission.id,
            "permalink": submission.permalink,
            "author": str(submission.author) if submission.author else None,
            "title": submission.title,
            "selftext": submission.selftext or "",
            "created_utc": submission.created_utc,
            "score": submission.score,
            "num_comments": submission.num_comments,
            "upvote_ratio": submission.upvote_ratio,
            "subreddit": str(submission.subreddit),
        }


class _ComposioBackend(_Backend):
    """Backend that routes Reddit calls through Composio's managed OAuth app.

    Uses two action slugs:
      - REDDIT_RETRIEVE_REDDIT_POST: list posts in a subreddit (sort=new)
      - REDDIT_SEARCH_ACROSS_SUBREDDITS: keyword search across all of reddit
    """

    SEARCH_SLUG = "REDDIT_SEARCH_ACROSS_SUBREDDITS"
    SUBREDDIT_SLUG = "REDDIT_RETRIEVE_REDDIT_POST"

    def __init__(self):
        self._client = None
        self._user_id: str | None = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from composio import Composio
        except ImportError as exc:
            raise RuntimeError("composio not installed; run pip install composio") from exc

        api_key = env("COMPOSIO_API_KEY")
        user_id = env("COMPOSIO_USER_ID")
        if not api_key or not user_id:
            raise RuntimeError(
                "Composio credentials missing. Set COMPOSIO_API_KEY and COMPOSIO_USER_ID in .env, "
                "or switch REDDIT_BACKEND=praw."
            )

        self._client = Composio(api_key=api_key)
        self._user_id = user_id
        return self._client

    def fetch_subreddit(self, name: str, limit: int) -> Iterable[dict[str, Any]]:
        client = self._get_client()
        result = client.tools.execute(
            slug=self.SUBREDDIT_SLUG,
            arguments={
                "subreddit": name,
                "sort": "new",
                "max_results": min(limit, 100),
            },
            user_id=self._user_id,
        )
        for raw in self._extract_posts(result):
            yield self._normalize(raw, default_subreddit=name)

    def fetch_search(self, term: str, limit: int) -> Iterable[dict[str, Any]]:
        client = self._get_client()
        result = client.tools.execute(
            slug=self.SEARCH_SLUG,
            arguments={
                "search_query": term,
                "sort": "new",
                "limit": min(limit, 100),
                "restrict_sr": False,
            },
            user_id=self._user_id,
        )
        for raw in self._extract_posts(result):
            yield self._normalize(raw)

    @staticmethod
    def _extract_posts(result: Any) -> list[dict[str, Any]]:
        """Pull the post list out of a Composio response.

        Composio returns {"data": ..., "successful": bool, "error": str?}.
        The shape of `data` for Reddit listings is the standard Reddit JSON
        envelope: {"data": {"children": [{"data": <post>}, ...]}}. We unwrap
        defensively so minor shape drift doesn't crash the poller.
        """
        if isinstance(result, dict):
            if result.get("successful") is False:
                raise RuntimeError(f"Composio call failed: {result.get('error')}")
            data = result.get("data", result)
        else:
            data = getattr(result, "data", result)

        # Reddit-style envelope
        if isinstance(data, dict) and "children" in data.get("data", {}):
            return [child.get("data", {}) for child in data["data"]["children"]]
        if isinstance(data, dict) and "children" in data:
            return [child.get("data", child) for child in data["children"]]
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "posts" in data:
            return data["posts"]
        return []

    @staticmethod
    def _normalize(raw: dict[str, Any], default_subreddit: str | None = None) -> dict[str, Any]:
        """Map a raw Composio post payload to the dict shape RedditSource expects."""
        return {
            "id": raw.get("id") or raw.get("post_id") or raw.get("name", "").removeprefix("t3_"),
            "permalink": raw.get("permalink") or raw.get("url", ""),
            "author": raw.get("author"),
            "title": raw.get("title") or "",
            "selftext": raw.get("selftext") or raw.get("body") or "",
            "created_utc": raw.get("created_utc") or raw.get("created") or 0,
            "score": raw.get("score") or raw.get("ups"),
            "num_comments": raw.get("num_comments"),
            "upvote_ratio": raw.get("upvote_ratio"),
            "subreddit": raw.get("subreddit") or default_subreddit or "",
        }
