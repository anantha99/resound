"""Apify-backed public listening source adapter."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from resound.core.source import SourceAdapter
from resound.models import RawSignal
from resound.social import APIFY_ACTORS, V1_PUBLIC_SOURCE_TYPES, normalize_apify_item

logger = logging.getLogger(__name__)


class ApifyPublicListeningSource(SourceAdapter):
    """Normalizes Apify public-listening payloads into ``RawSignal``.

    The first production slice accepts already-fetched payloads via params so
    workflows can own Apify run execution/retries without leaking provider
    payloads downstream. A later activity can replace ``items_by_source`` with
    real Apify API calls while preserving this adapter contract.
    """

    name = "apify"

    def poll(self) -> Iterable[RawSignal]:
        items_by_source = self.params.get("items_by_source") or {}
        run_ids = self.params.get("run_ids") or {}
        for source_type in sorted(V1_PUBLIC_SOURCE_TYPES):
            for item in items_by_source.get(source_type, []):
                try:
                    yield normalize_apify_item(
                        source_type=source_type,
                        item=item,
                        actor_id=APIFY_ACTORS[source_type],
                        run_id=run_ids.get(source_type),
                    )
                except ValueError as exc:
                    logger.warning("Skipping malformed Apify %s item: %s", source_type, exc)
