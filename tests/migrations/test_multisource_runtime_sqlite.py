from __future__ import annotations

from datetime import datetime

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


def test_populated_sqlite_migration_preserves_unrelated_health(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'populated.db'}"
    monkeypatch.setenv("RESOUND_DATABASE_URL", database_url)
    config = Config("alembic.ini")
    command.upgrade(config, "20260702_0005")
    engine = create_engine(database_url, future=True)
    now = datetime(2026, 7, 17, 12, 0, 0)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organizations (id,slug,display_name,created_at) "
                "VALUES (1,'org','Org',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO brands "
                "(id,organization_id,slug,display_name,description,source_config,"
                "created_at,updated_at) VALUES (1,1,'acme','Acme','',:config,:now,:now)"
            ),
            {"config": "{}", "now": now},
        )
        for source_type, provider in (("reddit", "legacy"), ("g2", "direct")):
            connection.execute(
                text(
                    "INSERT INTO source_health "
                    "(organization_id,brand_id,source_type,provider,status,item_count,updated_at) "
                    "VALUES (1,1,:source_type,:provider,'ok',3,:now)"
                ),
                {"source_type": source_type, "provider": provider, "now": now},
            )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT source_type, canonical_source, path, item_count "
                "FROM source_health ORDER BY source_type"
            )
        ).all()
    assert rows == [("g2", None, None, 3)]
