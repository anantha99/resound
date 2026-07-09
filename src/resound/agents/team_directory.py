"""Team directory context used by routing agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TeamOwner:
    owner_id: str
    label: str
    description: str
    destination: str | None = None
    owner_type: str = "channel"


@dataclass(frozen=True)
class TeamDirectory:
    owners: list[TeamOwner]
    default_owner_id: str
    review_owner_id: str

    @property
    def allowed_owner_ids(self) -> set[str]:
        return {owner.owner_id for owner in self.owners} | {"(none)"}

    def resolve(self, owner_id: str) -> str | None:
        for owner in self.owners:
            if owner.owner_id == owner_id:
                return owner.destination or owner.owner_id
        if owner_id == "(none)":
            return None
        return owner_id

    def prompt_context(self) -> str:
        lines = []
        for owner in self.owners:
            destination = f" destination={owner.destination}" if owner.destination else ""
            lines.append(
                f"- {owner.owner_id} ({owner.owner_type}): {owner.label}. "
                f"{owner.description}{destination}"
            )
        return "\n".join(lines)


GENERIC_TEAM_OWNERS: tuple[TeamOwner, ...] = (
    TeamOwner("#triage", "Triage", "Default intake queue for unclear ownership."),
    TeamOwner("#review-queue", "Review Queue", "Human review for low-confidence calls."),
    TeamOwner(
        "#incident-comms",
        "Incident Comms",
        "Urgent reliability, outage, or PR-risk coordination.",
    ),
    TeamOwner(
        "@eng-on-call",
        "Engineering On-call",
        "Bugs, reliability, performance, and technical failures.",
        owner_type="person",
    ),
    TeamOwner(
        "@product-lead",
        "Product Lead",
        "Roadmap, UX, feature requests, and product strategy.",
        owner_type="person",
    ),
    TeamOwner(
        "@support-lead",
        "Support Lead",
        "Customer support, education, account help, and workflow confusion.",
        owner_type="person",
    ),
    TeamOwner(
        "@revenue-ops",
        "Revenue Ops",
        "Pricing, billing, packaging, renewals, and commercial friction.",
        owner_type="person",
    ),
    TeamOwner(
        "@marketing-comms",
        "Marketing Comms",
        "Brand, launch, social, content, and positive advocacy opportunities.",
        owner_type="person",
    ),
    TeamOwner(
        "@trust-safety",
        "Trust and Safety",
        "Abuse, privacy, compliance, moderation, and safety issues.",
        owner_type="person",
    ),
)


def build_team_directory(
    *,
    people_config: dict[str, Any] | None,
    routing_config: dict[str, Any] | None,
) -> TeamDirectory:
    people_config = people_config or {}
    routing_config = routing_config or {}
    owners_by_id: dict[str, TeamOwner] = {owner.owner_id: owner for owner in GENERIC_TEAM_OWNERS}

    for owner_id, entry in (people_config.get("people") or {}).items():
        if not isinstance(entry, dict):
            continue
        owners_by_id[str(owner_id)] = TeamOwner(
            owner_id=str(owner_id),
            label=str(entry.get("name") or owner_id),
            description=str(
                entry.get("role") or entry.get("description") or "Brand-specific person."
            ),
            destination=entry.get("slack") or entry.get("email") or entry.get("name"),
            owner_type="person",
        )

    for owner_id, entry in (people_config.get("channels") or {}).items():
        if not isinstance(entry, dict):
            continue
        owners_by_id[str(owner_id)] = TeamOwner(
            owner_id=str(owner_id),
            label=str(entry.get("name") or owner_id),
            description=str(entry.get("description") or "Brand-specific channel."),
            destination=entry.get("slack_channel") or entry.get("name"),
            owner_type="channel",
        )

    default_owner_id = str(routing_config.get("default_route") or "#triage")
    _ensure_policy_owner(owners_by_id, default_owner_id, "Default route from routing policy.")
    for rule in routing_config.get("rules") or []:
        if not isinstance(rule, dict) or not rule.get("route_to"):
            continue
        _ensure_policy_owner(
            owners_by_id,
            str(rule["route_to"]),
            f"Routing-policy target for {rule.get('name') or 'unnamed rule'}.",
        )

    review_owner_id = "#review-queue" if "#review-queue" in owners_by_id else default_owner_id
    return TeamDirectory(
        owners=sorted(owners_by_id.values(), key=lambda owner: owner.owner_id),
        default_owner_id=default_owner_id,
        review_owner_id=review_owner_id,
    )


def _ensure_policy_owner(
    owners_by_id: dict[str, TeamOwner],
    owner_id: str,
    description: str,
) -> None:
    if owner_id in owners_by_id:
        return
    owners_by_id[owner_id] = TeamOwner(
        owner_id=owner_id,
        label=owner_id,
        description=description,
        destination=owner_id,
        owner_type="person" if owner_id.startswith("@") else "channel",
    )
