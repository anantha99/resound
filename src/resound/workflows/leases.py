"""Stable brand-workflow lease constants shared by start and activity code."""

from __future__ import annotations

PUBLIC_LISTENING_WORKFLOW_KIND = "public_listening_sync"
PUBLIC_LISTENING_LEASE_TTL_SECONDS = 120
PUBLIC_LISTENING_LEASE_RENEW_SECONDS = 30
PUBLIC_LISTENING_START_UNKNOWN_TTL_SECONDS = 600


def public_listening_workflow_id(
    organization_id: int,
    brand_id: int,
    workflow_job_id: int,
) -> str:
    if min(organization_id, brand_id, workflow_job_id) <= 0:
        raise ValueError("workflow identity values must be positive")
    return (
        f"public-listening-sync:org:{organization_id}:"
        f"brand:{brand_id}:job:{workflow_job_id}"
    )
