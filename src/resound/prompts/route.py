"""Routing prompt for the agentic signal triage flow."""

from __future__ import annotations

import json
from typing import Any

from resound.agents.team_directory import TeamDirectory
from resound.models import Classification, RawSignal

ROUTE_PROMPT_V1 = """You are Resound's routing agent.
Your job is to choose the best owner/team for one classified customer signal.

You must adapt to the brand's available organization structure.
Choose only from the allowed owners listed below.
If the signal is off-brand or should be ignored, choose "(none)".

# Brand context

{brand_context}

# Routing policy

{routing_policy}

# Allowed owners

{team_directory}

# Classification

{classification_json}

# Signal

Source: {source}
Posted: {posted_at}
Author: {author}
URL: {url}

---

{content}

---

# Output format

Return a single JSON object with exactly these fields:

{{
  "owner_id": "one allowed owner id, or (none)",
  "priority": "normal" or "immediate",
  "notes": "short explanation for why this team owns the signal",
  "confidence": float 0.0 to 1.0
}}

# Rules

- owner_id MUST be one of the allowed owners or "(none)".
- Use "immediate" only for critical incidents, urgent PR risk, severe customer impact,
  safety, privacy, or compliance issues.
- Prefer a specific team/person over a generic triage queue when ownership is clear.
- Use the review queue for low-confidence or ambiguous ownership.
- Return ONLY the JSON object. No preamble, no markdown fences."""


def build_route_prompt(
    *,
    raw: RawSignal,
    classification: Classification,
    brand_context: str,
    routing_config: dict[str, Any],
    team_directory: TeamDirectory,
) -> str:
    return ROUTE_PROMPT_V1.format(
        brand_context=brand_context or "(no additional context)",
        routing_policy=json.dumps(routing_config or {}, ensure_ascii=True, indent=2),
        team_directory=team_directory.prompt_context(),
        classification_json=classification.model_dump_json(),
        source=raw.source,
        posted_at=raw.posted_at.isoformat(),
        author=raw.author_handle or "(unknown)",
        url=raw.url or "(no url)",
        content=raw.content,
    )
