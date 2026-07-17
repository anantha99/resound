from __future__ import annotations

import os
import uuid

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, make_url, text


@pytest.fixture
def postgres_migration_harness(monkeypatch):
    database_url = os.environ.get("RESOUND_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("RESOUND_TEST_POSTGRES_URL is not explicitly configured")
    if not make_url(database_url).drivername.startswith("postgresql"):
        pytest.fail("RESOUND_TEST_POSTGRES_URL must be a PostgreSQL URL")

    schema = f"resound_task3_{uuid.uuid4().hex}"
    admin = create_engine(database_url, future=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_url = (
        make_url(database_url)
        .update_query_dict({"options": f"-csearch_path={schema}"})
        .render_as_string(hide_password=False)
    )
    monkeypatch.setenv("RESOUND_DATABASE_URL", test_url)
    config = Config("alembic.ini")
    try:
        yield test_url, config
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()
