"""Smoke tests for the Twitter source. We don't hit the real API; we verify
the no-token case fails gracefully and the import path works."""

from __future__ import annotations

from resound.sources.twitter import TwitterSource


def test_twitter_returns_empty_without_bearer_token(monkeypatch):
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    source = TwitterSource(
        brand_slug="fulfil",
        params={
            "handles": ["@fulfilio"],
            "search_terms": ["fulfil.io"],
        },
    )
    signals = list(source.poll())
    assert signals == []


def test_twitter_returns_empty_when_no_handles_or_terms(monkeypatch):
    monkeypatch.setenv("TWITTER_BEARER_TOKEN", "fake-token")
    source = TwitterSource(brand_slug="fulfil", params={})
    # _get_client will succeed (just returns a tweepy.Client object), but
    # poll() will short-circuit because there are no queries to run.
    try:
        signals = list(source.poll())
    except RuntimeError:
        # tweepy not installed in some test envs — that's fine, the
        # graceful-no-config case is what we're after.
        return
    assert signals == []


def test_twitter_caps_limit_at_api_max(monkeypatch):
    monkeypatch.delenv("TWITTER_BEARER_TOKEN", raising=False)
    source = TwitterSource(brand_slug="x", params={"limit": 500})
    assert source.limit == 100  # capped at 100, the API's per-request max
