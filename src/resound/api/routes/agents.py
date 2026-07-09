from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from resound.api import schemas
from resound.api.dependencies import get_memory, get_tenant_context
from resound.memory import SqlMemory
from resound.tenancy import TenantContext

router = APIRouter(tags=["agents"])


@router.get("/agents/sessions", operation_id="listAgentSessions")
def list_agent_sessions(
    memory: SqlMemory = Depends(get_memory),
    tenant: TenantContext | None = Depends(get_tenant_context),
) -> list[schemas.AgentSession]:
    if tenant is None:
        raise HTTPException(status_code=401, detail="Tenant context required")
    return [
        schemas.AgentSession(
            id=row.id,
            agent_type=row.agent_type,
            user_goal=row.user_goal,
            status=row.status,
            created_at=row.created_at.isoformat(),
        )
        for row in memory.list_agent_sessions_for_tenant(tenant)
    ]
