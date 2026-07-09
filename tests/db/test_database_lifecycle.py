from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from resound.api.dependencies import get_memory, reset_memory_cache
from resound.memory import SignalRow, SqlMemory
from resound.models import RawSignal


def test_sqlite_memory_creates_schema_for_local_tests(tmp_path):
    db_path = tmp_path / "local.db"
    memory = SqlMemory(database_url=f"sqlite:///{db_path}")

    signal_id = memory.record_signal(
        "liquiddeath",
        RawSignal(
            source="reddit",
            external_id="abc123",
            content="Shipping damage keeps happening.",
            posted_at=datetime.now(tz=UTC),
        ),
    )

    with memory.session() as session:
        row = session.execute(select(SignalRow).where(SignalRow.id == signal_id)).scalar_one()

    assert row.brand_slug == "liquiddeath"
    assert row.source == "reddit"


def test_api_memory_dependency_reuses_engine_for_same_database_url(tmp_path, monkeypatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{db_path}")
    reset_memory_cache()

    first = get_memory()
    second = get_memory()

    assert first is second
    assert first.engine is second.engine

    reset_memory_cache()


def test_postgres_memory_does_not_create_schema_implicitly(monkeypatch):
    calls: list[str] = []

    def fake_create_all(engine):
        calls.append(str(engine.url))

    monkeypatch.setattr("resound.memory.Base.metadata.create_all", fake_create_all)
    memory = SqlMemory(database_url="postgresql+psycopg://user:pass@localhost/resound")

    assert memory.engine.url.drivername == "postgresql+psycopg"
    assert calls == []
