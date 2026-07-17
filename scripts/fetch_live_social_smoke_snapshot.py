#!/usr/bin/env python3
"""Retrieve and verify the immutable live-social smoke SQLite snapshot."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

EXPECTED_SHA256 = "831cdbf5b5ca04a7b1548805d9fedda207ea8fd271f0dc90407af6ab1c884090"
TARGET = Path("data/resound-live-social-smoke.db")
CI_SOURCE_ENV = "RESOUND_LIVE_SOCIAL_SNAPSHOT_SOURCE"
REQUIRED_TABLES = {"organizations", "brands", "signals", "workflow_jobs", "source_health"}


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https":
            raise ValueError("snapshot redirect uses an unapproved scheme")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        help=f"Local path or HTTPS URL (or set {CI_SOURCE_ENV} in CI)",
    )
    args = parser.parse_args(argv)
    source = args.source or os.environ.get(CI_SOURCE_ENV)
    if source is None:
        if TARGET.is_file() and verify_snapshot(TARGET):
            print(f"Verified immutable snapshot: {TARGET}")
            return 0
        print(
            "BLOCKED: provide --source <local-path-or-https-url> or set "
            f"{CI_SOURCE_ENV} to retrieve the approved snapshot.",
            file=sys.stderr,
        )
        return 2

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    part = TARGET.with_suffix(TARGET.suffix + ".part")
    part.unlink(missing_ok=True)
    try:
        _stream_source(source, part)
        if not verify_snapshot(part):
            raise ValueError("snapshot SHA-256, SQLite integrity, or schema verification failed")
        os.replace(part, TARGET)
    except Exception as exc:
        part.unlink(missing_ok=True)
        print(f"Snapshot retrieval failed: {exc}", file=sys.stderr)
        return 1
    print(f"Installed immutable snapshot: {TARGET} ({EXPECTED_SHA256})")
    return 0


def _stream_source(source: str, destination: Path) -> None:
    parsed = urlparse(source)
    if parsed.scheme:
        if parsed.scheme != "https":
            raise ValueError("snapshot URL must use HTTPS")
        opener = urllib.request.build_opener(SafeRedirectHandler())
        with opener.open(source, timeout=60) as response, destination.open("xb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        return
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    with source_path.open("rb") as input_file, destination.open("xb") as output:
        shutil.copyfileobj(input_file, output, length=1024 * 1024)


def verify_snapshot(path: Path) -> bool:
    if _sha256(path) != EXPECTED_SHA256:
        return False
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            return False
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        return REQUIRED_TABLES <= tables
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
