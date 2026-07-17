from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from resound.cli import app
from resound.social.contracts import SourcePath


def test_cli_starts_the_resolved_request_with_selected_paths_and_lower_limits(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("RESOUND_DATABASE_URL", f"sqlite:///{tmp_path / 'cli.db'}")
    captured = {}

    async def fake_start(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            status="queued",
            workflow_id="public-listening-sync:org:1:brand:1:job:1",
            run_id="run-1",
        )

    monkeypatch.setattr("resound.cli.start_public_listening_workflow", fake_start)
    monkeypatch.setattr("resound.cli.build_workflow_starter", lambda: object())

    result = CliRunner().invoke(
        app,
        [
            "sync-public-listening",
            "--brand", "liquiddeath",
            "--organization", "cli-test",
            "--source", "instagram",
            "--path", "instagram:official_discovery",
            "--max-items", "7",
            "--max-signals-per-source", "6",
            "--max-runs-per-source", "2",
            "--max-cost-usd-per-source", "0.25",
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured["request_input"]
    assert request.selected_sources == ("instagram",)
    assert request.selected_paths[0].paths == (SourcePath.OFFICIAL_DISCOVERY,)
    assert request.limits.max_items_per_path == 7
    assert request.limits.max_signals_per_source == 6
    assert request.limits.max_runs_per_source == 2
    assert str(request.limits.max_cost_usd_per_source) == "0.25"
