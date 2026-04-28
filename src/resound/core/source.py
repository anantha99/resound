"""Layer 1: Ingestion. Every source is a SourceAdapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

from resound.models import RawSignal


class SourceAdapter(ABC):
    """Pulls raw customer signals from an external surface.

    Implementations:
      - Authenticate against the source.
      - Poll for new content given brand-specific parameters.
      - Normalize each item into a RawSignal.
      - Provide a deterministic dedupe key per item.
    """

    name: str  # e.g. "reddit", "g2", "twitter"

    def __init__(self, brand_slug: str, params: dict[str, Any]):
        self.brand_slug = brand_slug
        self.params = params

    @abstractmethod
    def poll(self) -> Iterable[RawSignal]:
        """Yield new signals discovered since the last poll. Stateless;
        the pipeline handles dedup against the memory layer."""
        ...

    def healthcheck(self) -> bool:
        """Return True if the adapter can authenticate. Default: try a
        trivial poll and check for exceptions."""
        try:
            list(self.poll())  # consume up to whatever the adapter returns
            return True
        except Exception:
            return False
