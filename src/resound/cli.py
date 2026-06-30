"""Resound CLI.

Usage:
    resound run --brand liquiddeath
    resound poll-once --brand liquiddeath
    resound dashboard --brand liquiddeath
    resound healthcheck --brand liquiddeath
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from resound.config import env, load_brand_config
from resound.gateway import load_models_config
from resound.pipeline import Pipeline

app = typer.Typer(add_completion=False, help="Resound — voice-of-customer routing.")
console = Console()


def _setup_logging() -> None:
    level = env("RESOUND_LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def poll_once(
    brand: str = typer.Option(..., help="Brand slug (matches brands/<slug>/)"),
) -> None:
    """Run the pipeline once and exit."""
    _setup_logging()
    cfg = load_brand_config(brand)
    pipeline = Pipeline(cfg)
    console.print(f"[bold cyan]Resound[/] running once for [bold]{cfg.name}[/]...")
    stats = pipeline.run_once()
    _print_stats(stats)


@app.command()
def run(
    brand: str = typer.Option(..., help="Brand slug"),
    interval_seconds: int = typer.Option(300, help="Seconds between polls"),
) -> None:
    """Run the pipeline on a loop. Ctrl-C to stop."""
    _setup_logging()
    cfg = load_brand_config(brand)
    pipeline = Pipeline(cfg)
    console.print(f"[bold cyan]Resound[/] daemon running for [bold]{cfg.name}[/].")
    console.print(f"Polling every {interval_seconds}s. Ctrl-C to stop.\n")
    try:
        while True:
            stats = pipeline.run_once()
            _print_stats(stats)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped by user.[/]")


@app.command()
def healthcheck(
    brand: str = typer.Option(..., help="Brand slug"),
) -> None:
    """Verify config files load and source adapters can authenticate."""
    _setup_logging()
    cfg = load_brand_config(brand)
    console.print(f"[bold]{cfg.name}[/] ({cfg.slug})")
    console.print(f"  description: {cfg.description}")
    console.print(f"  sources configured: {list(cfg.sources.keys())}")
    console.print(f"  routing rules: {len(cfg.routing.get('rules', []))}")
    console.print(f"  people entries: {len(cfg.people.get('people', {}))}")
    console.print(f"  channel entries: {len(cfg.people.get('channels', {}))}")
    console.print(f"  understanding doc: {len(cfg.understanding)} chars")

    global_cfg = load_models_config(brand_slug=None)
    brand_cfg = load_models_config(brand_slug=brand)
    classify = brand_cfg.get_stage_config("classify")
    global_classify_model = global_cfg.get_stage_config("classify").model

    if classify.model != global_classify_model:
        source = f"brand override (brands/{brand}/models.yaml)"
    else:
        source = "config/models.yaml (global default)"

    console.print(f"  classify model: {classify.model}")
    console.print(f"    source: {source}")
    fallback_str = ", ".join(classify.fallbacks) if classify.fallbacks else "(none)"
    console.print(f"    fallbacks: {fallback_str}")
    console.print(f"    timeout: {classify.timeout_s}s")

    if not env("OPENROUTER_API_KEY"):
        console.print("[red]✗ OPENROUTER_API_KEY not set[/]")
    else:
        console.print("[green]✓ OPENROUTER_API_KEY set[/]")

    reddit_cfg = cfg.sources.get("reddit", {})
    if reddit_cfg.get("enabled"):
        backend = (env("REDDIT_BACKEND") or "composio").strip().lower()
        console.print(f"  reddit backend: {backend}")
        if backend == "composio":
            for key in ("COMPOSIO_API_KEY", "COMPOSIO_USER_ID"):
                if not env(key):
                    console.print(f"[red]✗ {key} not set[/]")
                else:
                    console.print(f"[green]✓ {key} set[/]")
        elif backend == "praw":
            for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
                if not env(key):
                    console.print(f"[red]✗ {key} not set[/]")
                else:
                    console.print(f"[green]✓ {key} set[/]")
        else:
            console.print(f"[red]✗ unknown REDDIT_BACKEND={backend!r} (use composio or praw)[/]")


@app.command()
def dashboard(
    brand: str = typer.Option(..., help="Brand slug"),
    port: int = typer.Option(8501, help="Streamlit port"),
) -> None:
    """Launch the Streamlit dashboard for a brand."""
    here = Path(__file__).resolve().parent
    app_path = here / "dashboard" / "app.py"
    os.environ["RESOUND_BRAND"] = brand
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
    ]
    console.print(f"[bold cyan]Launching dashboard[/] for [bold]{brand}[/] on port {port}...")
    subprocess.run(cmd)


@app.command()
def api(
    host: str = typer.Option("127.0.0.1", help="API host"),
    port: int = typer.Option(8000, help="API port"),
    reload: bool = typer.Option(False, help="Enable uvicorn reload"),
) -> None:
    """Launch the FastAPI backend used by the web and mobile clients."""
    _setup_logging()
    import uvicorn

    console.print(f"[bold cyan]Launching Resound API[/] on http://{host}:{port}...")
    uvicorn.run("resound.api.app:app", host=host, port=port, reload=reload)


@app.command("export-openapi")
def export_openapi(
    output: Path = typer.Option(
        Path("Resound-UI/Builtiful-Interface/lib/api-spec/openapi.yaml"),
        "--output",
        "-o",
        help="File to write the frontend-facing OpenAPI schema to.",
    ),
) -> None:
    """Export the FastAPI contract for React client generation."""
    _setup_logging()
    import yaml

    from resound.api.openapi import client_openapi_schema

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(client_openapi_schema(), sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    console.print(f"[green]Wrote OpenAPI schema[/] to {output}")


def _print_stats(stats) -> None:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("polled", str(stats.polled))
    table.add_row("new", str(stats.new))
    table.add_row("classified", str(stats.classified))
    table.add_row("routed", str(stats.routed))
    table.add_row("ignored", str(stats.ignored))
    table.add_row("errors", str(stats.errors))
    console.print(table)


if __name__ == "__main__":
    app()
