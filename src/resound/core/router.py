"""Layer 3: Routing. Decide who sees a signal."""

from __future__ import annotations

from abc import ABC, abstractmethod

from resound.models import Classification, RawSignal, Route


class Router(ABC):
    """Given a signal and its classification, decide who handles it."""

    @abstractmethod
    def route(self, signal: RawSignal, classification: Classification) -> Route:
        ...
