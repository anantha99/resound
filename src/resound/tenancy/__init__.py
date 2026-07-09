"""Tenant context shared by API, workflows, and agents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    organization_id: int
    organization_slug: str
    team_id: int | None
    user_id: int | None

    @property
    def is_team_scoped(self) -> bool:
        return self.team_id is not None
