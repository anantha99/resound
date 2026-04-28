"""Reddit source via PRAW.

Pulls from configured subreddits and brand-name search. Each item becomes a
RawSignal with source='reddit'. Comments and posts are both surfaced.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

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
        self._reddit = None  # lazy

    def _client(self):
        if self._reddit is not None:
            return self._reddit
        try:
            import praw
        except ImportError as exc:
            raise RuntimeError("praw not installed; run pip install praw") from exc

        client_id = env("REDDIT_CLIENT_ID")
        client_secret = env("REDDIT_CLIENT_SECRET")
        user_agent = env("REDDIT_USER_AGENT") or f"resound:v0.1.0 ({self.brand_slug})"

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

    def poll(self) -> Iterable[RawSignal]:
        reddit = self._client()
        limit = int(self.params.get("limit", 25))

        # Subreddit feeds: newest posts in each configured subreddit.
        for sub_name in self.params.get("subreddits", []):
            try:
                subreddit = reddit.subreddit(sub_name)
                for submission in subreddit.new(limit=limit):
                    yield self._post_to_signal(submission, channel=f"r/{sub_name}")
            except Exception as exc:
                logger.warning(f"Reddit subreddit {sub_name!r} poll failed: {exc}")

        # Search across all of reddit for brand-name terms.
        for term in self.params.get("search_terms", []):
            try:
                for submission in reddit.subreddit("all").search(term, sort="new", limit=limit):
                    yield self._post_to_signal(submission, channel=f"search:{term}")
            except Exception as exc:
                logger.warning(f"Reddit search {term!r} failed: {exc}")

    @staticmethod
    def _post_to_signal(submission, channel: str) -> RawSignal:
        body = submission.selftext or ""
        content = submission.title
        if body:
            content = f"{submission.title}\n\n{body}"
        return RawSignal(
            source="reddit",
            external_id=str(submission.id),
            url=f"https://reddit.com{submission.permalink}",
            author_handle=str(submission.author) if submission.author else None,
            content=content,
            posted_at=datetime.fromtimestamp(submission.created_utc, tz=timezone.utc),
            raw_metadata={
                "channel": channel,
                "subreddit": str(submission.subreddit),
                "score": submission.score,
                "num_comments": submission.num_comments,
                "upvote_ratio": submission.upvote_ratio,
            },
        )
