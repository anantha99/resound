"""File-based feedback channel.

Writes each routed signal as a JSONL row under data/routes/<brand>/<date>.jsonl.
Humans review the file, mark `correct: true/false` and `actioned: true/false`,
and the dashboard reads back through Memory."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from resound.core.feedback import FeedbackChannel
from resound.models import Classification, RawSignal, Route

logger = logging.getLogger(__name__)


class FileFeedback(FeedbackChannel):
    """Append-only JSONL writer."""

    def __init__(self, brand_slug: str, base_dir: Path | None = None):
        self.brand_slug = brand_slug
        self.base_dir = base_dir or Path("data/routes") / brand_slug
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def notify(
        self,
        signal: RawSignal,
        classification: Classification,
        route: Route,
        signal_id: int,
        route_id: int,
    ) -> None:
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        out_path = self.base_dir / f"{date_str}.jsonl"

        entry = {
            "signal_id": signal_id,
            "route_id": route_id,
            "routed_at": datetime.utcnow().isoformat(),
            "owner_id": route.owner_id,
            "destination": route.destination,
            "matched_rule": route.matched_rule,
            "priority": route.priority,
            "source": signal.source,
            "url": signal.url,
            "author": signal.author_handle,
            "posted_at": signal.posted_at.isoformat(),
            "summary": classification.summary,
            "area": classification.area,
            "severity": classification.severity.value,
            "action_class": classification.action_class.value,
            "sentiment": classification.sentiment.value,
            "confidence": classification.confidence,
            "content": signal.content[:500],
        }

        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info(
            "ROUTE → %s [%s] %s :: %s",
            route.owner_id,
            classification.action_class.value,
            classification.area,
            classification.summary,
        )
