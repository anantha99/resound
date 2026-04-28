"""Layer 5: Feedback / learning loop."""

from __future__ import annotations

from abc import ABC, abstractmethod

from resound.models import Classification, RawSignal, Route


class FeedbackChannel(ABC):
    """Notifies the routed owner and (eventually) collects feedback.

    v1 implementations are write-only (file, console). Future implementations
    (Slack, email digest, dashboard) collect feedback events that flow back
    into Memory."""

    @abstractmethod
    def notify(
        self,
        signal: RawSignal,
        classification: Classification,
        route: Route,
        signal_id: int,
        route_id: int,
    ) -> None:
        ...
