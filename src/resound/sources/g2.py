"""G2 reviews source.

Scrapes the public reviews page at https://www.g2.com/products/<slug>/reviews.

IMPORTANT CAVEATS:
  - G2 actively rate-limits and Cloudflare-protects. This adapter is suitable
    for low-volume polling (a few dozen reviews per day per brand). For
    production use, replace with G2's official API (paid) or a buyer-intent
    feed if the brand subscribes.
  - HTML structure changes; selectors are conservative and degrade gracefully.
    If a selector returns no matches, the adapter logs and continues — never
    crashes the pipeline.

Polling strategy:
  - One request per page. Default: just page 1 (newest reviews).
  - Throttle: 2 seconds between requests minimum.
  - Retry once on 403/429 with backoff, then give up and return what we have.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from resound.core.source import SourceAdapter
from resound.models import RawSignal

logger = logging.getLogger(__name__)


# Realistic browser-style headers. G2 blocks the default httpx user-agent.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class G2Source(SourceAdapter):
    """Polls G2 product review pages.

    params (sources.yaml):
      product_slug: G2 URL slug, e.g., 'fulfil' for g2.com/products/fulfil
      max_pages: how many review pages to fetch per poll (default 1)
      throttle_seconds: delay between page fetches (default 2)
    """

    name = "g2"
    BASE_URL = "https://www.g2.com/products/{slug}/reviews"

    def __init__(self, brand_slug: str, params: dict):
        super().__init__(brand_slug, params)
        self.product_slug = params.get("product_slug", "").strip()
        self.max_pages = int(params.get("max_pages", 1))
        self.throttle = float(params.get("throttle_seconds", 2.0))

    def poll(self) -> Iterable[RawSignal]:
        if not self.product_slug:
            logger.warning("G2Source: no product_slug configured for %s", self.brand_slug)
            return

        signals: list[RawSignal] = []

        with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20) as client:
            for page in range(1, self.max_pages + 1):
                url = self._page_url(page)
                html = self._fetch(client, url)
                if not html:
                    break

                page_signals = self._parse_reviews(html, source_url=url)
                if not page_signals:
                    logger.info("G2Source: no reviews parsed from %s", url)
                    break
                signals.extend(page_signals)

                if page < self.max_pages:
                    time.sleep(self.throttle)

        return signals

    # --- helpers ---

    def _page_url(self, page: int) -> str:
        base = self.BASE_URL.format(slug=self.product_slug)
        return base if page == 1 else f"{base}?page={page}"

    def _fetch(self, client: httpx.Client, url: str) -> str | None:
        for attempt in (1, 2):
            try:
                r = client.get(url)
            except httpx.RequestError as exc:
                logger.warning("G2 request error for %s: %s", url, exc)
                return None

            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 429):
                logger.warning(
                    "G2 returned %s for %s (attempt %d). Backing off.",
                    r.status_code, url, attempt,
                )
                if attempt == 1:
                    time.sleep(5.0)
                    continue
                logger.warning("G2 blocked. Giving up on this poll cycle.")
                return None
            logger.warning("G2 unexpected status %s for %s", r.status_code, url)
            return None
        return None

    def _parse_reviews(self, html: str, source_url: str) -> list[RawSignal]:
        soup = BeautifulSoup(html, "html.parser")

        # G2 review cards have changed layout multiple times. We try a few
        # selectors and pick whichever yields results.
        cards = (
            soup.select("[itemprop='review']")
            or soup.select("[data-testid='review-card']")
            or soup.select("article.paper")
            or soup.select("div.review")
        )

        signals: list[RawSignal] = []
        for card in cards:
            sig = self._card_to_signal(card, source_url)
            if sig is not None:
                signals.append(sig)
        return signals

    def _card_to_signal(self, card, source_url: str) -> RawSignal | None:
        # Review ID — usually anchor link or data-attribute on the card.
        external_id = (
            card.get("data-id")
            or card.get("id")
            or self._extract_review_id(card)
        )
        if not external_id:
            return None

        # Title — often an h3 or h4 inside the card.
        title_el = card.select_one("h3, h4, [itemprop='name']")
        title = title_el.get_text(" ", strip=True) if title_el else ""

        # Body — pros/cons/comments. G2 separates these into multiple sections.
        body_parts: list[str] = []
        for label, selector in [
            ("Review", "[itemprop='reviewBody']"),
            ("Pros", "[data-testid='pros']"),
            ("Cons", "[data-testid='cons']"),
            ("Recommendations", "[data-testid='recommendations']"),
        ]:
            el = card.select_one(selector)
            if el:
                txt = el.get_text(" ", strip=True)
                if txt:
                    body_parts.append(f"{label}: {txt}")

        # Fallback: grab all paragraph text inside the card.
        if not body_parts:
            paras = card.select("p")
            for p in paras:
                t = p.get_text(" ", strip=True)
                if t and len(t) > 20:
                    body_parts.append(t)

        body = "\n\n".join(body_parts).strip()
        if not body and not title:
            return None

        content = f"{title}\n\n{body}".strip() if title else body

        # Author handle — G2 shows display name + role + company.
        author_el = card.select_one("[itemprop='author'], [data-testid='reviewer-name']")
        author = author_el.get_text(" ", strip=True) if author_el else None

        # Posted date — from [datetime] attribute.
        date_el = card.select_one("[itemprop='datePublished'], time")
        posted_at = self._parse_date(date_el)

        # Rating — when present, store in metadata; we don't surface it as
        # severity directly (the classifier decides severity).
        rating = self._extract_rating(card)

        # Permalink — G2 review cards have a "permalink" anchor.
        link_el = card.select_one("a[href*='/reviews/']")
        url = None
        if link_el and link_el.get("href"):
            href = link_el["href"]
            url = href if href.startswith("http") else f"https://www.g2.com{href}"

        return RawSignal(
            source="g2",
            external_id=str(external_id),
            url=url or source_url,
            author_handle=author,
            content=content,
            posted_at=posted_at,
            raw_metadata={
                "product_slug": self.product_slug,
                "rating": rating,
                "title": title,
            },
        )

    @staticmethod
    def _extract_review_id(card) -> str | None:
        # Look for a permalink anchor like /reviews/foo-review-12345
        link = card.select_one("a[href*='/reviews/']")
        if link and link.get("href"):
            m = re.search(r"-(\d+)(?:\?|$|/)", link["href"])
            if m:
                return m.group(1)
            return link["href"].rstrip("/").split("/")[-1]
        return None

    @staticmethod
    def _parse_date(el) -> datetime:
        if el is None:
            return datetime.now(tz=timezone.utc)
        for attr in ("datetime", "content", "data-date"):
            v = el.get(attr) if hasattr(el, "get") else None
            if v:
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00"))
                except ValueError:
                    pass
        text = el.get_text(strip=True) if hasattr(el, "get_text") else ""
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _extract_rating(card) -> float | None:
        rating_el = card.select_one("[data-rating], [aria-label*='Rated']")
        if rating_el is None:
            return None
        for attr in ("data-rating", "aria-label"):
            v = rating_el.get(attr)
            if not v:
                continue
            m = re.search(r"(\d+(?:\.\d+)?)", v)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
        return None
