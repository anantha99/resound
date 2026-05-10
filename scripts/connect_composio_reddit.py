"""One-time Composio OAuth bootstrap for Reddit.

Reads COMPOSIO_API_KEY and COMPOSIO_USER_ID from .env, prints a redirect URL
to authorize Reddit, and waits for the OAuth callback. After it succeeds the
RedditSource (composio backend) can poll Reddit for the configured user_id.

Run once per Composio user_id. Re-run if the connection ever expires or
landed in a non-ACTIVE state (e.g. FAILED from a 429 during OAuth).

    uv run python scripts/connect_composio_reddit.py

Pass --reset to delete any non-ACTIVE Reddit connections before retrying:

    uv run python scripts/connect_composio_reddit.py --reset
"""

from __future__ import annotations

import sys

from resound.config import env


def _is_reddit(account) -> bool:
    toolkit = getattr(account, "toolkit", None)
    slug = getattr(toolkit, "slug", None) if toolkit is not None else None
    if slug is None:
        slug = getattr(account, "toolkit_slug", None) or getattr(account, "auth_config", None)
    return str(slug).lower() == "reddit"


def main(argv: list[str]) -> int:
    api_key = env("COMPOSIO_API_KEY")
    user_id = env("COMPOSIO_USER_ID")
    if not api_key or not user_id:
        print("ERROR: COMPOSIO_API_KEY and COMPOSIO_USER_ID must be set in .env", file=sys.stderr)
        return 1

    try:
        from composio import Composio
    except ImportError:
        print("ERROR: composio not installed. Run: uv sync", file=sys.stderr)
        return 1

    reset = "--reset" in argv

    client = Composio(api_key=api_key)

    existing = client.connected_accounts.list(user_ids=[user_id])
    items = list(getattr(existing, "items", existing) or [])
    reddit_accounts = [a for a in items if _is_reddit(a)]
    active = [a for a in reddit_accounts if str(getattr(a, "status", "")).upper() == "ACTIVE"]
    stale = [a for a in reddit_accounts if str(getattr(a, "status", "")).upper() != "ACTIVE"]

    if active:
        print(f"Reddit is already ACTIVE for user_id={user_id!r}:")
        for acc in active:
            print(f"  - id={getattr(acc, 'id', '?')}  status={getattr(acc, 'status', '?')}")
        return 0

    if stale:
        print(f"Found {len(stale)} non-ACTIVE Reddit connection(s) for user_id={user_id!r}:")
        for acc in stale:
            print(f"  - id={getattr(acc, 'id', '?')}  status={getattr(acc, 'status', '?')}")
        if not reset:
            print("\nDelete them and retry with: --reset")
            print("Or run again later (Reddit OAuth 429s usually clear in 10-15 min).")
            return 2
        for acc in stale:
            acc_id = getattr(acc, "id", None)
            if not acc_id:
                continue
            try:
                client.connected_accounts.delete(acc_id)
                print(f"  deleted {acc_id}")
            except Exception as exc:
                print(f"  failed to delete {acc_id}: {exc}", file=sys.stderr)

    session = client.create(user_id=user_id)
    request = session.authorize("reddit")

    print(f"\nUser ID: {user_id}")
    print("Open this URL in your browser to authorize Reddit:\n")
    print(f"  {request.redirect_url}\n")
    print("Waiting for OAuth completion (2-min timeout)...")

    connection = request.wait_for_connection(120000)
    print(f"\nConnected. account_id={connection.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
