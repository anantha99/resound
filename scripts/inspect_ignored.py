"""Print every signal whose route is 'ignored_by_classifier'.

Read-only inspection of the local SQLite DB. Useful for auditing whether
the classifier is correctly filtering off-topic search hits vs. wrongly
ignoring real brand mentions.

    uv run python scripts/inspect_ignored.py
    uv run python scripts/inspect_ignored.py --since-id 50
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import textwrap


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--since-id",
        type=int,
        default=0,
        help="Only show signals with id > this value (filters to a recent batch).",
    )
    args = parser.parse_args(argv)

    conn = sqlite3.connect("./data/resound.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.id, s.url, s.content,
               c.is_about_brand, c.area, c.sentiment, c.severity,
               c.action_class, c.summary, c.confidence
        FROM signals s
        JOIN classifications c ON c.signal_id = s.id
        JOIN routes r ON r.signal_id = s.id
        WHERE r.matched_rule = 'ignored_by_classifier'
          AND s.id > ?
        ORDER BY s.id DESC
        """,
        (args.since_id,),
    ).fetchall()

    print(f"\n{len(rows)} ignored signals\n")
    for r in rows:
        print(f"--- signal #{r['id']} ---")
        print(f"  url:       {r['url']}")
        print(
            f"  about LD?: {bool(r['is_about_brand'])}"
            f"   area={r['area']}"
            f"   sentiment={r['sentiment']}"
            f"   confidence={r['confidence']:.2f}"
        )
        print(f"  summary:   {r['summary']}")
        content = (r["content"] or "").replace("\n", " ")
        print(f"  content:   {textwrap.shorten(content, 240)}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
