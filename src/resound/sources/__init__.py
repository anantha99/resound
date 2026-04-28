"""Source adapters. Adding a new source = add a class + register here."""

from __future__ import annotations

from typing import Any

from resound.core.source import SourceAdapter
from resound.sources.g2 import G2Source
from resound.sources.reddit import RedditSource
from resound.sources.twitter import TwitterSource

REGISTRY: dict[str, type[SourceAdapter]] = {
    "reddit": RedditSource,
    "g2": G2Source,
    "twitter": TwitterSource,
}


def build_sources(brand_slug: str, sources_config: dict[str, Any]) -> list[SourceAdapter]:
    """Instantiate adapters listed in sources.yaml."""
    adapters: list[SourceAdapter] = []
    for name, params in (sources_config or {}).items():
        if not params or params.get("enabled") is False:
            continue
        cls = REGISTRY.get(name)
        if cls is None:
            raise ValueError(f"Unknown source: {name!r}. Known: {list(REGISTRY)}")
        adapters.append(cls(brand_slug=brand_slug, params=params))
    return adapters


__all__ = ["RedditSource", "G2Source", "TwitterSource", "REGISTRY", "build_sources"]
