"""FastAPI dependencies."""

from __future__ import annotations

from resound.memory import SqlMemory


def get_memory() -> SqlMemory:
    return SqlMemory()
