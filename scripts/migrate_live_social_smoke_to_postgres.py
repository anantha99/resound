"""Import the version-pinned live-social smoke snapshot into a fresh Postgres schema.

The snapshot contains IDs embedded in signal dedupe keys, so importing through
domain methods would corrupt its audit relationships. This script copies rows
verbatim, in foreign-key order, inside a single transaction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from math import isclose, isfinite
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    String,
    create_engine,
    func,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Connection

from resound.memory import Base

SOURCE_DATABASE = Path("data/resound-live-social-smoke.db")
EXPECTED_SOURCE_SHA256 = "831cdbf5b5ca04a7b1548805d9fedda207ea8fd271f0dc90407af6ab1c884090"
EXPECTED_ALEMBIC_REVISION = "20260717_0006"
SOURCE_TABLE_ORDER = (
    "organizations",
    "users",
    "teams",
    "brands",
    "memberships",
    "signals",
    "listening_profiles",
    "agent_sessions",
    "report_configs",
    "workflow_jobs",
    "source_health",
    "classifications",
    "llm_calls",
    "public_feed_moderation_events",
    "listening_profile_suggestions",
    "listening_profile_revisions",
    "agent_steps",
    "report_runs",
    "workflow_events",
    "routes",
    "feedback_events",
    "route_handoffs",
    "report_citations",
)
TABLE_ORDER = (*SOURCE_TABLE_ORDER, "workflow_leases")
NEW_COLUMNS = {
    "signals": {
        "canonical_platform",
        "content_kind",
        "provider_native_id",
        "fallback_identity_hash",
    },
    "workflow_jobs": {
        "resolved_config_snapshot",
        "request_fingerprint_summary",
        "result_schema_version",
        "result_summary",
        "start_reconciliation_diagnostics",
    },
    "source_health": {
        "canonical_source",
        "path",
        "fetched_count",
        "processed_count",
        "duplicate_count",
        "cost_usd",
        "provenance",
        "issues",
    },
}
PUBLIC_HEALTH_ALIASES = {
    "reddit",
    "instagram_public",
    "instagram",
    "tiktok",
    "x_public",
    "x",
    "twitter",
    "youtube_comments",
    "youtube",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Import into the configured Postgres database. The default runs source preflight only."
        ),
    )
    args = parser.parse_args()

    load_dotenv()
    source_hash, source_rows = _read_source(SOURCE_DATABASE)
    _print_report(source_hash, source_rows)

    if not args.execute:
        print("Preflight passed. Run Alembic, then repeat with --execute to import.")
        return

    database_url = os.environ.get("RESOUND_DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql"):
        raise SystemExit("RESOUND_DATABASE_URL must be a PostgreSQL URL before importing.")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            _validate_target(connection)
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('resound-live-social-import'))"),
            )

            for table_name in TABLE_ORDER:
                rows = source_rows[table_name]
                if rows:
                    connection.execute(Base.metadata.tables[table_name].insert(), rows)

            _validate_target_rows(connection, source_rows)
            _reset_sequences(connection)
    finally:
        engine.dispose()

    imported_rows = sum(len(rows) for rows in source_rows.values())
    print(f"Imported {imported_rows} rows from {SOURCE_DATABASE}.")


def _read_source(source_path: Path) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    if not source_path.is_file():
        raise SystemExit(f"Source database not found: {source_path}")
    if set(Base.metadata.tables) != set(TABLE_ORDER):
        raise SystemExit("Importer table manifest no longer matches the application schema.")

    source_hash = _file_hash(source_path)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise SystemExit("Source SHA-256 does not match the approved smoke snapshot.")
    connection = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Source SQLite integrity check failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise SystemExit("Source SQLite foreign-key check failed.")

        source_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'",
            )
        }
        if source_tables != set(SOURCE_TABLE_ORDER):
            raise SystemExit("Source table manifest does not match the expected smoke snapshot.")

        source_rows: dict[str, list[dict[str, Any]]] = {}
        for table_name in SOURCE_TABLE_ORDER:
            table = Base.metadata.tables[table_name]
            source_columns = [
                row[1] for row in connection.execute(f'PRAGMA table_info("{table_name}")')
            ]
            expected_columns = [
                column.name
                for column in table.columns
                if column.name not in NEW_COLUMNS.get(table_name, set())
            ]
            if source_columns != expected_columns:
                raise SystemExit(f"Source columns drifted for {table_name}.")
            source_rows[table_name] = [
                _transform_source_row(table_name, table, dict(row))
                for row in connection.execute(f'SELECT * FROM "{table_name}" ORDER BY id')
            ]
        source_rows["source_health"] = [
            row for row in source_rows["source_health"] if row is not None
        ]
        source_rows["workflow_leases"] = []
    finally:
        connection.close()

    if _file_hash(source_path) != source_hash:
        raise SystemExit("Source database changed while it was being read.")
    return source_hash, source_rows


def _transform_source_row(table_name: str, table, row: dict[str, Any]) -> dict[str, Any] | None:
    transformed = {
        column.name: _normalize_value(column, row[column.name])
        for column in table.columns
        if column.name in row
    }
    if table_name == "signals":
        metadata = transformed.get("raw_metadata") or {}
        platform = _canonical_platform(metadata.get("canonical_platform"))
        kind = metadata.get("content_kind")
        native = metadata.get("provider_native_id")
        fallback = metadata.get("fallback_identity_hash")
        if not platform or not kind or bool(native) == bool(fallback):
            platform = kind = native = fallback = None
        transformed.update(
            canonical_platform=platform,
            content_kind=str(kind).lower() if kind else None,
            provider_native_id=str(native) if native else None,
            fallback_identity_hash=str(fallback).lower() if fallback else None,
        )
    elif table_name == "workflow_jobs":
        transformed.update(
            resolved_config_snapshot=None,
            request_fingerprint_summary=None,
            result_schema_version=None,
            result_summary=None,
            start_reconciliation_diagnostics=None,
        )
    elif table_name == "source_health":
        if (
            transformed.get("provider") == "apify"
            or transformed.get("source_type") in PUBLIC_HEALTH_ALIASES
        ):
            return None
        raise SystemExit(
            "Source snapshot contains legacy health whose flat path cannot be inferred safely."
        )
    return transformed


def _canonical_platform(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"twitter", "x", "x_public"}:
        return "x"
    return {
        "reddit": "reddit",
        "instagram": "instagram",
        "instagram_public": "instagram",
        "tiktok": "tiktok",
        "youtube": "youtube",
        "youtube_comments": "youtube",
    }.get(normalized)


def _normalize_row(table, row: dict[str, Any]) -> dict[str, Any]:
    return {column.name: _normalize_value(column, row[column.name]) for column in table.columns}


def _normalize_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, Boolean):
        if value not in (0, 1, False, True):
            raise SystemExit(f"Invalid boolean value for {column.table.name}.{column.name}.")
        return bool(value)
    if isinstance(column.type, DateTime):
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise SystemExit(f"Invalid datetime value for {column.table.name}.{column.name}.")
        if parsed.tzinfo is not None:
            raise SystemExit(f"Timezone-aware datetime found in {column.table.name}.{column.name}.")
        return parsed
    if isinstance(column.type, JSON):
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            json.dumps(parsed, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Invalid JSON value for {column.table.name}.{column.name}.") from exc
        return parsed
    if isinstance(column.type, Float):
        if not isinstance(value, (int, float)) or not isfinite(value):
            raise SystemExit(f"Invalid float value for {column.table.name}.{column.name}.")
        return float(value)
    if isinstance(column.type, String):
        if not isinstance(value, str) or "\x00" in value:
            raise SystemExit(f"Invalid text value for {column.table.name}.{column.name}.")
        if column.type.length is not None and len(value) > column.type.length:
            raise SystemExit(f"Oversize value for {column.table.name}.{column.name}.")
    return value


def _validate_target(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        raise SystemExit("Target must be PostgreSQL.")

    table_names = set(inspect(connection).get_table_names(schema="public"))
    missing_tables = set(TABLE_ORDER) - table_names
    if missing_tables:
        raise SystemExit(f"Target is missing migrated tables: {', '.join(sorted(missing_tables))}")

    revision = connection.execute(
        text("SELECT version_num FROM alembic_version"),
    ).scalar_one_or_none()
    if revision != EXPECTED_ALEMBIC_REVISION:
        raise SystemExit(
            f"Target Alembic revision must be {EXPECTED_ALEMBIC_REVISION}, found {revision!r}.",
        )

    for table_name in TABLE_ORDER:
        table = Base.metadata.tables[table_name]
        target_columns = {column["name"] for column in inspect(connection).get_columns(table_name)}
        if target_columns != set(table.columns.keys()):
            raise SystemExit(f"Target columns drifted for {table_name}.")
        if connection.scalar(select(func.count()).select_from(table)):
            raise SystemExit(f"Target table is not empty: {table_name}")


def _reset_sequences(connection: Connection) -> None:
    for table_name in TABLE_ORDER:
        quoted_table = f'"{table_name}"'
        sequence_name = connection.scalar(
            text(f"SELECT pg_get_serial_sequence('public.{table_name}', 'id')"),
        )
        if sequence_name:
            connection.execute(
                text(
                    f"SELECT setval(:sequence_name, "
                    f"COALESCE((SELECT MAX(id) FROM {quoted_table}), 1), "
                    f"EXISTS (SELECT 1 FROM {quoted_table}))",
                ),
                {"sequence_name": sequence_name},
            )


def _validate_target_rows(
    connection: Connection,
    source_rows: dict[str, list[dict[str, Any]]],
) -> None:
    for table_name in TABLE_ORDER:
        table = Base.metadata.tables[table_name]
        target_rows = [
            _normalize_row(table, dict(row))
            for row in connection.execute(select(table).order_by(table.c.id)).mappings()
        ]
        if not _rows_match(table, source_rows[table_name], target_rows):
            raise SystemExit(f"Target data validation failed for {table_name}.")


def _print_report(source_hash: str, source_rows: dict[str, list[dict[str, Any]]]) -> None:
    print(f"Source SHA-256: {source_hash}")
    for table_name in TABLE_ORDER:
        print(f"{table_name}: {len(source_rows[table_name])} rows")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows_match(
    table,
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
) -> bool:
    if len(source_rows) != len(target_rows):
        return False
    for source_row, target_row in zip(source_rows, target_rows, strict=True):
        for column in table.columns:
            source_value = source_row[column.name]
            target_value = target_row[column.name]
            if isinstance(column.type, Float):
                if source_value is None or target_value is None:
                    if source_value != target_value:
                        return False
                elif not isclose(source_value, target_value, rel_tol=1e-12, abs_tol=1e-12):
                    return False
            elif source_value != target_value:
                return False
    return True


if __name__ == "__main__":
    main()
