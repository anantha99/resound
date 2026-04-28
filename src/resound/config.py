"""Load brand configuration from disk."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class BrandConfig:
    """A complete brand configuration bundle."""

    slug: str  # directory name, e.g., "liquiddeath"
    brand: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    people: dict[str, Any] = field(default_factory=dict)
    views: dict[str, Any] = field(default_factory=dict)
    understanding: str = ""

    @property
    def name(self) -> str:
        return self.brand.get("name", self.slug)

    @property
    def description(self) -> str:
        return self.brand.get("description", "")


def load_brand_config(brand_slug: str, brands_dir: Path | None = None) -> BrandConfig:
    """Load a complete brand bundle from brands/<slug>/."""
    brands_dir = brands_dir or Path("brands")
    brand_dir = brands_dir / brand_slug

    if not brand_dir.is_dir():
        raise FileNotFoundError(f"Brand directory not found: {brand_dir}")

    def _load_yaml(name: str) -> dict[str, Any]:
        p = brand_dir / name
        if not p.exists():
            return {}
        with p.open() as f:
            return yaml.safe_load(f) or {}

    understanding_path = brand_dir / "understanding.md"
    understanding = (
        understanding_path.read_text() if understanding_path.exists() else ""
    )

    return BrandConfig(
        slug=brand_slug,
        brand=_load_yaml("brand.yaml"),
        sources=_load_yaml("sources.yaml"),
        routing=_load_yaml("routing.yaml"),
        people=_load_yaml("people.yaml"),
        views=_load_yaml("views.yaml"),
        understanding=understanding,
    )


def env(name: str, default: str | None = None) -> str | None:
    """Read an env var, with default."""
    return os.environ.get(name, default)


def require_env(name: str) -> str:
    """Read an env var, raise if missing."""
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env and fill in the values."
        )
    return val
