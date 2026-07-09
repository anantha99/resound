from __future__ import annotations

from pathlib import Path

from resound.ops.configuration import runtime_configuration_status


def test_configuration_status_reports_missing_required_secrets(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("RESOUND_DATABASE_URL", "sqlite:///./data/resound.db")
    monkeypatch.setenv("RESOUND_TEMPORAL_ADDRESS", "127.0.0.1:7233")

    status = runtime_configuration_status()

    assert status["database"] == "configured"
    assert status["temporal"] == "configured"
    assert status["openrouter"] == "missing"


def test_production_deployment_artifacts_exist():
    assert Path("Dockerfile").exists()
    assert "temporal" in Path("docker-compose.yml").read_text(encoding="utf-8")
    assert Path("docs/runbooks/production-backend.md").exists()
    assert Path("docs/runbooks/temporal-workers.md").exists()
