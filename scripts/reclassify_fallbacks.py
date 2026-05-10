"""A/B test current classifier + router against historical signals.

Two modes:
  --ids 10,2          → target specific signal ids (any prior classification)
  (default)           → pull every fallback row (confidence=0.0 AND
                        summary LIKE '[classifier fallback%')

For each signal, re-runs the *currently configured* classifier (per
config/models.yaml + brand override) AND the *currently configured*
router (per brand routing.yaml), then prints old vs new classification
and routing side-by-side.

Read-only: does NOT write back to the DB. Cost is roughly N × one
classify call (~$0.003 each on Sonnet 4.6).

Examples:
    uv run python scripts/reclassify_fallbacks.py --brand liquiddeath
    uv run python scripts/reclassify_fallbacks.py --brand liquiddeath --ids 10,2
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime

from resound.classifiers import build_classifier
from resound.config import load_brand_config
from resound.models import RawSignal
from resound.routers import RulesRouter


def row_to_signal(row: sqlite3.Row) -> RawSignal:
    posted_at = row["posted_at"]
    if isinstance(posted_at, str):
        posted_at = datetime.fromisoformat(posted_at)
    return RawSignal(
        source=row["source"],
        external_id=row["external_id"],
        url=row["url"],
        author_handle=row["author_handle"],
        content=row["content"],
        posted_at=posted_at,
        raw_metadata=json.loads(row["raw_metadata"]) if row["raw_metadata"] else {},
    )


def parse_ids(spec: str | None) -> list[int]:
    if not spec:
        return []
    return [int(x.strip()) for x in spec.split(",") if x.strip()]


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", required=True)
    parser.add_argument(
        "--ids",
        type=str,
        default=None,
        help="Comma-separated signal ids to target (e.g. '10,2'). "
        "Overrides the default fallback-only filter.",
    )
    parser.add_argument(
        "--limit", type=int, default=20, help="Cap how many to re-run (cost control)."
    )
    args = parser.parse_args(argv)

    target_ids = parse_ids(args.ids)

    brand = load_brand_config(args.brand)
    classifier = build_classifier(brand.slug)
    router = RulesRouter(brand.routing, brand.people)

    conn = sqlite3.connect("./data/resound.db")
    conn.row_factory = sqlite3.Row

    if target_ids:
        placeholders = ",".join("?" * len(target_ids))
        rows = conn.execute(
            f"""
            SELECT s.id, s.source, s.external_id, s.url, s.author_handle,
                   s.content, s.posted_at, s.raw_metadata,
                   c.is_about_brand AS old_is_about, c.area AS old_area,
                   c.sentiment AS old_sentiment, c.severity AS old_severity,
                   c.action_class AS old_action, c.summary AS old_summary,
                   c.confidence AS old_conf,
                   r.owner_id AS old_owner, r.matched_rule AS old_rule
            FROM signals s
            JOIN classifications c ON c.signal_id = s.id
            JOIN routes r ON r.signal_id = s.id
            WHERE s.id IN ({placeholders})
            ORDER BY s.id DESC
            """,
            target_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT s.id, s.source, s.external_id, s.url, s.author_handle,
                   s.content, s.posted_at, s.raw_metadata,
                   c.is_about_brand AS old_is_about, c.area AS old_area,
                   c.sentiment AS old_sentiment, c.severity AS old_severity,
                   c.action_class AS old_action, c.summary AS old_summary,
                   c.confidence AS old_conf,
                   r.owner_id AS old_owner, r.matched_rule AS old_rule
            FROM signals s
            JOIN classifications c ON c.signal_id = s.id
            JOIN routes r ON r.signal_id = s.id
            WHERE c.confidence = 0.0
              AND c.summary LIKE '[classifier fallback%'
            ORDER BY s.id DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()

    if not rows:
        print("No matching signals found.")
        return 0

    print(f"Re-running {len(rows)} signal(s) through current classifier + router")
    print(f"(brand={args.brand}, models per config/models.yaml, rules per brand routing.yaml)\n")

    changed_class = 0
    changed_route = 0
    for row in rows:
        raw = row_to_signal(row)
        preview = raw.content.replace("\n", " ")[:140]
        print(f"--- signal #{row['id']} ---")
        print(f"  url:       {row['url']}")
        print(f"  preview:   {preview}")
        print(
            f"  old class: is_about={bool(row['old_is_about'])}"
            f"  area={row['old_area']}  sentiment={row['old_sentiment']}"
            f"  severity={row['old_severity']}  action={row['old_action']}"
            f"  conf={row['old_conf']:.2f}"
        )
        print(f"  old route: owner={row['old_owner']}  rule={row['old_rule']}")
        print(f"  old summary: {row['old_summary']}")

        try:
            new_cls, _resp = classifier.classify(raw, brand.understanding)
            new_route = router.route(raw, new_cls)

            class_diff = (
                row["old_area"] != new_cls.area
                or row["old_sentiment"] != new_cls.sentiment.value
                or row["old_severity"] != new_cls.severity.value
                or row["old_action"] != new_cls.action_class.value
            )
            route_diff = (
                (row["old_owner"] or "") != (new_route.owner_id or "")
                or (row["old_rule"] or "") != (new_route.matched_rule or "")
            )
            if class_diff:
                changed_class += 1
            if route_diff:
                changed_route += 1

            ctag = "△ changed" if class_diff else "= same"
            rtag = "△ changed" if route_diff else "= same"
            print(
                f"  new class: is_about={new_cls.is_about_brand}"
                f"  area={new_cls.area}  sentiment={new_cls.sentiment.value}"
                f"  severity={new_cls.severity.value}"
                f"  action={new_cls.action_class.value}"
                f"  conf={new_cls.confidence:.2f}  {ctag}"
            )
            print(f"  new route: owner={new_route.owner_id}  rule={new_route.matched_rule}  {rtag}")
            print(f"  new summary: {new_cls.summary}")
        except Exception as exc:
            print(f"  new:       ERROR {type(exc).__name__}: {exc}")
        print()

    total = len(rows)
    print("=" * 60)
    print(f"Classification changed: {changed_class}/{total}")
    print(f"Routing changed:        {changed_route}/{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
