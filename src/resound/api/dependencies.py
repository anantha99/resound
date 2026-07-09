"""FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Header, HTTPException

from resound.config import env
from resound.db import configured_database_url
from resound.memory import SqlMemory
from resound.tenancy import TenantContext
from resound.workflows.client import WorkflowStarter, build_workflow_starter


def get_memory() -> SqlMemory:
    return _memory_for_url(configured_database_url())


def reset_memory_cache() -> None:
    _memory_for_url.cache_clear()


@lru_cache(maxsize=8)
def _memory_for_url(database_url: str) -> SqlMemory:
    return SqlMemory(database_url=database_url)


def get_workflow_starter() -> WorkflowStarter:
    return build_workflow_starter()


def get_tenant_context(
    organization_slug: Annotated[str | None, Header(alias="X-Resound-Organization")] = None,
    team_slug: Annotated[str | None, Header(alias="X-Resound-Team")] = None,
    user_external_id: Annotated[str | None, Header(alias="X-Resound-User")] = None,
) -> TenantContext | None:
    if not organization_slug:
        if _requires_tenant_header():
            raise HTTPException(status_code=401, detail="Tenant context required")
        return None

    memory = get_memory()
    organization_id = memory.ensure_organization(organization_slug, organization_slug)
    team_id = memory.ensure_team(organization_id, team_slug, team_slug) if team_slug else None
    user_id = None
    if user_external_id:
        user_id = memory.ensure_user(user_external_id)
        memory.ensure_membership(
            organization_id=organization_id,
            team_id=team_id,
            user_id=user_id,
        )
    return TenantContext(
        organization_id=organization_id,
        organization_slug=organization_slug.strip().lower(),
        team_id=team_id,
        user_id=user_id,
    )


def _requires_tenant_header() -> bool:
    return (env("RESOUND_REQUIRE_TENANT_HEADER", "false") or "false").lower() in {
        "1",
        "true",
        "yes",
    }
