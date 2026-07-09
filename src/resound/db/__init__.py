"""Database engine and session lifecycle helpers."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, make_url
from sqlalchemy.engine import URL
from sqlalchemy.orm import sessionmaker

from resound.config import env

DEFAULT_DATABASE_URL = "sqlite:///./data/resound.db"


def configured_database_url() -> str:
    return env("RESOUND_DATABASE_URL", DEFAULT_DATABASE_URL) or DEFAULT_DATABASE_URL


def is_sqlite_database_url(database_url: str | URL) -> bool:
    return make_url(str(database_url)).drivername.startswith("sqlite")


def create_database_engine(database_url: str | None = None) -> Engine:
    url = database_url or configured_database_url()
    _ensure_sqlite_parent(url)
    return create_engine(url, echo=False, future=True)


def create_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(engine, future=True, expire_on_commit=False)


def _ensure_sqlite_parent(database_url: str) -> None:
    url = make_url(database_url)
    if not url.drivername.startswith("sqlite"):
        return
    if not url.database or url.database == ":memory:":
        return
    Path(url.database).parent.mkdir(parents=True, exist_ok=True)
