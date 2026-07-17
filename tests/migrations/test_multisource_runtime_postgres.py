from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from alembic import command
from sqlalchemy import create_engine, inspect, make_url, text

from resound.memory import SqlMemory
from resound.models import RawSignal

ALIASES = (
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


def test_fresh_postgres_migration(postgres_migration_harness):
    database_url, config, schema = postgres_migration_harness
    command.upgrade(config, "head")
    engine = create_engine(
        database_url, future=True, connect_args={"options": f"-csearch_path={schema}"}
    )
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == "20260717_0006"
            )
            assert "workflow_leases" in inspect(connection).get_table_names()
            indexes = {item["name"] for item in inspect(connection).get_indexes("signals")}
            assert "uq_signals_provider_native_identity" in indexes
            assert "uq_signals_fallback_identity" in indexes
    finally:
        engine.dispose()


def test_populated_postgres_reset_and_collision_merge(postgres_migration_harness):
    database_url, config, schema = postgres_migration_harness
    command.upgrade(config, "20260702_0005")
    engine = create_engine(
        database_url, future=True, connect_args={"options": f"-csearch_path={schema}"}
    )
    now = datetime(2026, 7, 17, 12, 0, 0)
    metadata = json.dumps({"provider_native_id": "tweet-1", "content_kind": "post"})
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
                "created_at,updated_at) "
                "VALUES (1,1,'acme','Acme','',CAST('{}' AS jsonb),:now,:now)"
            ),
            {"now": now},
        )
        for index, alias in enumerate(ALIASES, 1):
            connection.execute(
                text(
                    "INSERT INTO source_health "
                    "(organization_id,brand_id,source_type,provider,status,item_count,updated_at) "
                    "VALUES (1,1,:alias,:provider,'ok',1,:now)"
                ),
                {
                    "alias": alias,
                    "provider": "legacy" if alias == "reddit" else "apify",
                    "now": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO source_health "
                "(organization_id,brand_id,source_type,provider,status,item_count,updated_at) "
                "VALUES (1,1,'g2','direct','ok',3,:now)"
            ),
            {"now": now},
        )
        for signal_id, source in ((1, "twitter"), (2, "x")):
            connection.execute(
                text(
                    "INSERT INTO signals "
                    "(id,organization_id,brand_id,brand_slug,source,source_mode,provider,"
                    "external_id,dedupe_key,url,content,posted_at,raw_metadata,ingested_at) "
                    "VALUES (:id,1,1,'acme',:source,'public_listening','apify',"
                    ":external,:dedupe,'https://x.test/1','same',:now,"
                    "CAST(:metadata AS jsonb),:now)"
                ),
                {
                    "id": signal_id,
                    "source": source,
                    "external": f"synthetic-{signal_id}",
                    "dedupe": f"{source}::synthetic-{signal_id}",
                    "metadata": metadata,
                    "now": now,
                },
            )
        connection.execute(
            text(
                "INSERT INTO classifications "
                "(id,signal_id,is_about_brand,area,sentiment,severity,action_class,"
                "summary,confidence,classified_at) "
                "VALUES (2,2,true,'engineering','negative','high','sprint',"
                "'summary',0.9,:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO routes (id,signal_id,classification_id,owner_id,priority,routed_at) "
                "VALUES (2,2,2,'@owner','normal',:now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO llm_calls "
                "(id,organization_id,brand_id,brand_slug,signal_id,stage,prompt_hash,"
                "latency_ms,was_fallback,attempt_count,success,called_at) "
                "VALUES (1,1,1,'acme',1,'classify','hash',1,false,1,true,:now)"
            ),
            {"now": now},
        )
    command.upgrade(config, "head")
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM source_health")) == 1
            retained_health = connection.execute(
                text(
                    "SELECT source_type, canonical_source, path, item_count "
                    "FROM source_health"
                )
            ).one()
            assert retained_health == ("g2", None, None, 3)
            assert connection.scalar(text("SELECT count(*) FROM signals")) == 1
            assert connection.scalar(text("SELECT id FROM signals")) == 2
            assert connection.scalar(text("SELECT signal_id FROM llm_calls WHERE id=1")) == 2
    finally:
        engine.dispose()


def test_concurrent_postgres_alias_insert_has_one_identity(postgres_migration_harness):
    database_url, config, schema = postgres_migration_harness
    command.upgrade(config, "head")
    scoped_url = (
        make_url(database_url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    memory = SqlMemory(database_url=scoped_url, create_schema=False)
    organization_id = memory.ensure_organization("org", "Org")
    brand = memory.ensure_brand(organization_id, "acme", "Acme")
    now = datetime.now().astimezone()

    def insert(source: str) -> int:
        return memory.record_signal(
            "acme",
            RawSignal(
                source=source,
                external_id=f"synthetic-{source}",
                content="same",
                posted_at=now,
                raw_metadata={
                    "canonical_platform": source,
                    "content_kind": "post",
                    "provider_native_id": "tweet-concurrent",
                },
            ),
            organization_id=organization_id,
            brand_id=brand.id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(insert, ("twitter", "x")))
    with memory.engine.connect() as connection:
        count = connection.scalar(
            text("SELECT count(*) FROM signals WHERE provider_native_id='tweet-concurrent'")
        )
    assert ids[0] == ids[1]
    assert count == 1
