"""Tests for the G2 source parser. Uses a saved HTML fixture so we don't hit
the real network — this also means the test fails loudly when G2 changes their
HTML, which is exactly what we want."""

from __future__ import annotations

from pathlib import Path

from resound.sources.g2 import G2Source

FIXTURE = Path(__file__).parent / "fixtures" / "g2_fulfil_reviews.html"


def test_g2_parser_extracts_three_reviews():
    html = FIXTURE.read_text()
    source = G2Source(brand_slug="fulfil", params={"product_slug": "fulfil"})
    signals = source._parse_reviews(html, source_url="https://www.g2.com/products/fulfil/reviews")

    assert len(signals) == 3, f"expected 3 signals, got {len(signals)}"

    # Check the second review (the negative one) carefully — it's the
    # interesting case for routing.
    negative = signals[1]
    assert negative.source == "g2"
    assert negative.external_id == "9876544"
    assert "Multi-warehouse allocation is broken" in negative.content
    assert "freight class" in negative.content
    assert negative.author_handle == "Mike R., Logistics Lead"
    assert negative.url and "fulfil-review-9876544" in negative.url
    assert negative.raw_metadata["rating"] == 2.0
    assert negative.raw_metadata["product_slug"] == "fulfil"


def test_g2_parser_handles_dates():
    html = FIXTURE.read_text()
    source = G2Source(brand_slug="fulfil", params={"product_slug": "fulfil"})
    signals = source._parse_reviews(html, source_url="x")
    # Dates in the fixture are 2026-04-12, 2026-04-10, 2026-04-08
    assert signals[0].posted_at.year == 2026
    assert signals[0].posted_at.month == 4
    assert signals[0].posted_at.day == 12


def test_g2_parser_returns_empty_on_garbage_html():
    source = G2Source(brand_slug="x", params={"product_slug": "x"})
    signals = source._parse_reviews("<html><body>nothing here</body></html>", source_url="x")
    assert signals == []


def test_g2_dedupe_keys_are_stable():
    html = FIXTURE.read_text()
    source = G2Source(brand_slug="fulfil", params={"product_slug": "fulfil"})
    signals = source._parse_reviews(html, source_url="x")
    keys = [s.dedupe_key() for s in signals]
    assert len(set(keys)) == 3  # all unique
    assert all(k.startswith("g2::") for k in keys)
