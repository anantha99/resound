"""Add multi-source identity, leases, flat health, and durable workflow state.

Revision ID: 20260717_0006
Revises: 20260702_0005
Create Date: 2026-07-17
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260717_0006"
down_revision = "20260702_0005"
branch_labels = None
depends_on = None

PUBLIC_HEALTH_ALIASES = (
    "reddit",
    "instagram_public",
    "instagram",
    "tiktok",
    "x_public",
    "x",
    "twitter",
    "youtube_comments",
    "youtube",
)


def upgrade() -> None:
    _add_workflow_runtime()
    _add_signal_identity()
    connection = op.get_bind()
    _backfill_resolvable_identity(connection)
    _merge_identity_collisions(connection)
    with op.batch_alter_table("signals") as batch:
        batch.create_check_constraint(
            "ck_signals_canonical_identity_complete",
            "(canonical_platform IS NULL AND content_kind IS NULL "
            "AND provider_native_id IS NULL AND fallback_identity_hash IS NULL) OR "
            "(organization_id IS NOT NULL AND brand_id IS NOT NULL "
            "AND canonical_platform IS NOT NULL AND content_kind IS NOT NULL "
            "AND ((provider_native_id IS NOT NULL AND fallback_identity_hash IS NULL) "
            "OR (provider_native_id IS NULL AND fallback_identity_hash IS NOT NULL)))",
        )
    op.create_index(
        "uq_signals_provider_native_identity",
        "signals",
        [
            "organization_id",
            "brand_id",
            "canonical_platform",
            "content_kind",
            "provider_native_id",
        ],
        unique=True,
        postgresql_where=sa.text("provider_native_id IS NOT NULL"),
        sqlite_where=sa.text("provider_native_id IS NOT NULL"),
    )
    op.create_index(
        "uq_signals_fallback_identity",
        "signals",
        [
            "organization_id",
            "brand_id",
            "canonical_platform",
            "content_kind",
            "fallback_identity_hash",
        ],
        unique=True,
        postgresql_where=sa.text("fallback_identity_hash IS NOT NULL"),
        sqlite_where=sa.text("fallback_identity_hash IS NOT NULL"),
    )
    _reset_and_flatten_health(connection)


def downgrade() -> None:
    raise RuntimeError(
        "20260717_0006 is forward-only; restore the pre-migration database snapshot instead"
    )


def _add_workflow_runtime() -> None:
    for name, column in (
        (
            "resolved_config_snapshot",
            sa.Column("resolved_config_snapshot", sa.JSON(), nullable=True),
        ),
        (
            "request_fingerprint_summary",
            sa.Column("request_fingerprint_summary", sa.JSON(), nullable=True),
        ),
        ("result_schema_version", sa.Column("result_schema_version", sa.Integer(), nullable=True)),
        ("result_summary", sa.Column("result_summary", sa.JSON(), nullable=True)),
        (
            "start_reconciliation_diagnostics",
            sa.Column("start_reconciliation_diagnostics", sa.JSON(), nullable=True),
        ),
    ):
        op.add_column("workflow_jobs", column)

    op.create_table(
        "workflow_leases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False
        ),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("workflow_kind", sa.String(length=64), nullable=False),
        sa.Column("owner_token", sa.String(length=128), nullable=False),
        sa.Column(
            "workflow_job_id", sa.Integer(), sa.ForeignKey("workflow_jobs.id"), nullable=False
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("renewed_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "brand_id", "workflow_kind", name="uq_workflow_leases_scope"
        ),
    )
    for column in (
        "organization_id",
        "brand_id",
        "workflow_kind",
        "owner_token",
        "workflow_job_id",
        "status",
        "expires_at",
    ):
        op.create_index(f"ix_workflow_leases_{column}", "workflow_leases", [column])


def _add_signal_identity() -> None:
    for column in (
        sa.Column("canonical_platform", sa.String(length=32), nullable=True),
        sa.Column("content_kind", sa.String(length=32), nullable=True),
        sa.Column("provider_native_id", sa.String(length=256), nullable=True),
        sa.Column("fallback_identity_hash", sa.String(length=64), nullable=True),
    ):
        op.add_column("signals", column)
        op.create_index(f"ix_signals_{column.name}", "signals", [column.name])


def _backfill_resolvable_identity(connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT id, organization_id, brand_id, source, url, content, posted_at, raw_metadata "
            "FROM signals WHERE organization_id IS NOT NULL AND brand_id IS NOT NULL ORDER BY id"
        )
    ).mappings()
    for row in rows:
        metadata = row["raw_metadata"] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        platform = _canonical_platform(metadata.get("canonical_platform") or row["source"])
        content_kind = metadata.get("content_kind") or _unambiguous_content_kind(platform)
        if not platform or not content_kind:
            continue
        native_id = metadata.get("provider_native_id")
        fallback_hash = metadata.get("fallback_identity_hash")
        if native_id and fallback_hash:
            continue
        if not native_id and not fallback_hash:
            fallback_hash = _legacy_fallback_hash(row, metadata, platform, str(content_kind))
        if not native_id and not fallback_hash:
            continue
        connection.execute(
            sa.text(
                "UPDATE signals SET canonical_platform=:platform, content_kind=:kind, "
                "provider_native_id=:native, fallback_identity_hash=:fallback WHERE id=:id"
            ),
            {
                "platform": platform,
                "kind": str(content_kind).strip().lower(),
                "native": str(native_id).strip() if native_id else None,
                "fallback": str(fallback_hash).strip().lower() if fallback_hash else None,
                "id": row["id"],
            },
        )


def _canonical_platform(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"twitter", "x", "x_public"}:
        return "x"
    aliases = {
        "reddit": "reddit",
        "instagram": "instagram",
        "instagram_public": "instagram",
        "tiktok": "tiktok",
        "youtube": "youtube",
        "youtube_comments": "youtube",
    }
    return aliases.get(normalized)


def _unambiguous_content_kind(platform: str) -> str | None:
    return {"reddit": "post", "x": "post", "tiktok": "video", "youtube": "video"}.get(platform)


def _legacy_fallback_hash(row, metadata, platform: str, content_kind: str) -> str | None:
    timestamp = metadata.get("provider_timestamp")
    if not row["url"] or not row["content"] or not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    payload = {
        "canonical_url": str(row["url"]).strip(),
        "content": " ".join(str(row["content"]).split()),
        "content_kind": content_kind.strip().lower(),
        "platform": platform,
        "provider_timestamp": parsed.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _merge_identity_collisions(connection) -> None:
    rows = connection.execute(
        sa.text(
            "SELECT s.id, s.organization_id, s.brand_id, s.canonical_platform, s.content_kind, "
            "s.provider_native_id, s.fallback_identity_hash, s.ingested_at, "
            "c.id AS classification_id, r.id AS route_id "
            "FROM signals s LEFT JOIN classifications c ON c.signal_id=s.id "
            "LEFT JOIN routes r ON r.signal_id=s.id "
            "WHERE s.provider_native_id IS NOT NULL OR s.fallback_identity_hash IS NOT NULL "
            "ORDER BY s.id"
        )
    ).mappings()
    groups: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    for row in rows:
        identity_kind = "native" if row["provider_native_id"] is not None else "fallback"
        identity_value = row["provider_native_id"] or row["fallback_identity_hash"]
        groups[
            (
                row["organization_id"],
                row["brand_id"],
                row["canonical_platform"],
                row["content_kind"],
                identity_kind,
                identity_value,
            )
        ].append(row)
    for group in groups.values():
        if len(group) < 2:
            continue
        winner = min(group, key=_collision_rank)
        for loser in sorted(
            (row for row in group if row["id"] != winner["id"]), key=lambda r: r["id"]
        ):
            _merge_signal_graph(connection, winner, loser)


def _collision_rank(row) -> tuple[Any, ...]:
    stage = 2 if row["route_id"] is not None else 1 if row["classification_id"] is not None else 0
    return (-stage, row["ingested_at"] or datetime.max, row["id"])


def _merge_signal_graph(connection, winner, loser) -> None:
    for table in ("llm_calls", "public_feed_moderation_events", "report_citations"):
        connection.execute(
            sa.text(f"UPDATE {table} SET signal_id=:winner WHERE signal_id=:loser"),
            {"winner": winner["id"], "loser": loser["id"]},
        )
    if loser["route_id"] is not None:
        for table in ("feedback_events", "route_handoffs"):
            connection.execute(
                sa.text(f"UPDATE {table} SET route_id=:winner WHERE route_id=:loser"),
                {"winner": winner["route_id"], "loser": loser["route_id"]},
            )
        connection.execute(sa.text("DELETE FROM routes WHERE id=:id"), {"id": loser["route_id"]})
    if loser["classification_id"] is not None:
        connection.execute(
            sa.text("DELETE FROM classifications WHERE id=:id"),
            {"id": loser["classification_id"]},
        )
    connection.execute(sa.text("DELETE FROM signals WHERE id=:id"), {"id": loser["id"]})


def _reset_and_flatten_health(connection) -> None:
    connection.execute(
        sa.text(
            "DELETE FROM source_health WHERE provider='apify' OR source_type IN :aliases"
        ).bindparams(sa.bindparam("aliases", expanding=True)),
        {"aliases": PUBLIC_HEALTH_ALIASES},
    )
    remaining = connection.execute(sa.text("SELECT count(*) FROM source_health")).scalar_one()
    if remaining:
        raise RuntimeError(
            "source_health contains legacy rows whose flat path cannot be inferred safely"
        )
    with op.batch_alter_table("source_health") as batch:
        batch.drop_constraint("uq_source_health_scope", type_="unique")
        batch.add_column(sa.Column("canonical_source", sa.String(length=32), nullable=False))
        batch.add_column(sa.Column("path", sa.String(length=32), nullable=False))
        batch.add_column(
            sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("provenance", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("issues", sa.JSON(), nullable=False, server_default="[]"))
        batch.create_unique_constraint(
            "uq_source_health_flat_path",
            ["organization_id", "brand_id", "canonical_source", "path"],
        )
    for column in ("canonical_source", "path"):
        op.create_index(f"ix_source_health_{column}", "source_health", [column])
