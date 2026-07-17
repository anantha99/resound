from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.fetch_live_social_smoke_snapshot import main


def test_missing_snapshot_is_explicitly_blocked(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RESOUND_LIVE_SOCIAL_SNAPSHOT_SOURCE", raising=False)
    assert main([]) == 2
    assert "BLOCKED:" in capsys.readouterr().err


def test_wrong_hash_is_rejected_without_installing_partial_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "wrong.db"
    source.write_bytes(b"not the approved snapshot")
    assert main(["--source", str(source)]) == 1
    assert not Path("data/resound-live-social-smoke.db").exists()
    assert not Path("data/resound-live-social-smoke.db.part").exists()


def test_command_uses_required_blocked_exit_code(tmp_path):
    script = Path(__file__).parents[2] / "scripts" / "fetch_live_social_smoke_snapshot.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "BLOCKED:" in completed.stderr
