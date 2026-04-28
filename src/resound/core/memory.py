"""Layer 4: Memory. Append-only persistence; the asset that compounds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from resound.models import Classification, FeedbackEvent, RawSignal, Route


class Memory(ABC):
    """The append-only store of every signal, classification, route,
    feedback event, and outcome. Implementations may use SQL, NoSQL, or
    cloud-managed stores; the contract is the same."""

    @abstractmethod
    def has_seen(self, dedupe_key: str) -> bool:
        ...

    @abstractmethod
    def record_signal(self, brand_slug: str, raw: RawSignal) -> int:
        """Persist a raw signal and return its primary key."""
        ...

    @abstractmethod
    def record_classification(self, signal_id: int, classification: Classification) -> int:
        ...

    @abstractmethod
    def record_route(self, signal_id: int, classification_id: int, route: Route) -> int:
        ...

    @abstractmethod
    def record_feedback(self, event: FeedbackEvent) -> int:
        ...

    @abstractmethod
    def query_recent(self, brand_slug: str, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent signals with their classifications and routes joined.
        Used by the dashboard."""
        ...
