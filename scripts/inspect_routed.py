"""Print every signal whose route was NOT 'ignored_by_classifier'.

Read-only inspection of routed (forwarded-to-channel) signals. Lets you
audit two things:
  1. Was the classification accurate (area / sentiment / severity / action)?
  2. Was the routing decision correct (right owner / channel for that classification)?

    uv run python scripts/inspect_routed.py
    uv run python scripts/inspect_routed.py --since-id 50
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
               c.is_about_brand, c.area, c.subarea, c.sentiment, c.severity,
               c.action_class, c.summary, c.confidence,
               r.owner_id, r.destination, r.matched_rule, r.priority
        FROM signals s
        JOIN classifications c ON c.signal_id = s.id
        JOIN routes r ON r.signal_id = s.id
        WHERE r.matched_rule != 'ignored_by_classifier'
          AND s.id > ?
        ORDER BY s.id DESC
        """,
        (args.since_id,),
    ).fetchall()

    print(f"\n{len(rows)} routed signals\n")

    # tally for end-of-run distribution view
    by_owner: dict[str, int] = {}
    by_area: dict[str, int] = {}
    by_action: dict[str, int] = {}

    for r in rows:
        owner = r["owner_id"] or "(none)"
        area = r["area"] or "(none)"
        action = r["action_class"] or "(none)"
        by_owner[owner] = by_owner.get(owner, 0) + 1
        by_area[area] = by_area.get(area, 0) + 1
        by_action[action] = by_action.get(action, 0) + 1

        print(f"--- signal #{r['id']} ---")
        print(f"  url:       {r['url']}")
        print(
            f"  classify:  is_about={bool(r['is_about_brand'])}"
            f"  area={r['area']}"
            f"  subarea={r['subarea']}"
            f"  sentiment={r['sentiment']}"
            f"  severity={r['severity']}"
            f"  action={r['action_class']}"
            f"  conf={r['confidence']:.2f}"
        )
        print(
            f"  route:     owner={r['owner_id']}"
            f"  dest={r['destination']}"
            f"  rule={r['matched_rule']}"
            f"  priority={r['priority']}"
        )
        print(f"  summary:   {r['summary']}")
        content = (r["content"] or "").replace("\n", " ")
        print(f"  content:   {textwrap.shorten(content, 240)}")
        print()

    print("=" * 60)
    print("Distribution:")
    print(f"  by owner:   {dict(sorted(by_owner.items(), key=lambda kv: -kv[1]))}")
    print(f"  by area:    {dict(sorted(by_area.items(), key=lambda kv: -kv[1]))}")
    print(f"  by action:  {dict(sorted(by_action.items(), key=lambda kv: -kv[1]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
