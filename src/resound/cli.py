"""Resound CLI.

Usage:
    resound run --brand liquiddeath
    resound poll-once --brand liquiddeath
    resound dashboard --brand liquiddeath
    resound healthcheck --brand liquiddeath
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

import typer
from rich.console import Console
from rich.table import Table

from resound.config import env, load_brand_config
from resound.gateway import load_models_config
from resound.memory import SqlMemory
from resound.ops.demo_population import (
    DEMO_BRANDS,
    MAX_ITEMS_LIMIT,
    DemoPopulationAlreadyRunningError,
    build_brand_listening_profile,
    populate_demo_brands,
)
from resound.pipeline import Pipeline
from resound.social import V1_PUBLIC_SOURCE_TYPES, SourceType
from resound.tenancy import TenantContext
from resound.workflows.public_listening import (
    PublicListeningSyncRequest,
)
from resound.workflows.public_listening import (
    sync_public_listening as run_public_listening_sync,
)

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
        console.print("[red]FAIL OPENROUTER_API_KEY not set[/]")
    else:
        console.print("[green]OK OPENROUTER_API_KEY set[/]")

    reddit_cfg = cfg.sources.get("reddit", {})
    if reddit_cfg.get("enabled"):
        backend = (env("REDDIT_BACKEND") or "composio").strip().lower()
        console.print(f"  reddit backend: {backend}")
        if backend == "composio":
            for key in ("COMPOSIO_API_KEY", "COMPOSIO_USER_ID"):
                if not env(key):
                    console.print(f"[red]FAIL {key} not set[/]")
                else:
                    console.print(f"[green]OK {key} set[/]")
        elif backend == "praw":
            for key in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"):
                if not env(key):
                    console.print(f"[red]FAIL {key} not set[/]")
                else:
                    console.print(f"[green]OK {key} set[/]")
        else:
            console.print(f"[red]FAIL unknown REDDIT_BACKEND={backend!r} (use composio or praw)[/]")


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


@app.command("sync-public-listening")
def sync_public_listening_cmd(
    brand: str = typer.Option(..., help="Brand slug (matches brands/<slug>/)"),
    organization: str = typer.Option("demo", help="Organization slug to seed/use"),
    sources: list[str] | None = typer.Option(
        None,
        "--source",
        help="Public source to sync. Repeat or comma-separate. Defaults to reddit.",
    ),
    max_items: int = typer.Option(20, min=1, help="Maximum Apify items per source"),
) -> None:
    """Seed a tenant brand/profile and run the Apify-backed public-listening sync."""
    _setup_logging()
    cfg = load_brand_config(brand)
    enabled_sources = _parse_public_sources(sources)
    memory = SqlMemory()
    organization_id = memory.ensure_organization(organization, organization.title())
    brand_row = memory.ensure_brand(
        organization_id,
        cfg.slug,
        cfg.name,
        description=cfg.description,
        source_config=cfg.sources,
    )
    memory.save_listening_profile(
        organization_id=organization_id,
        brand_id=brand_row.id,
        profile=build_brand_listening_profile(cfg, enabled_sources),
        authored_by="agent",
    )

    console.print(
        f"[bold cyan]Syncing public listening[/] brand=[bold]{cfg.slug}[/] "
        f"sources={enabled_sources} max_items={max_items}"
    )
    result = run_public_listening_sync(
        PublicListeningSyncRequest(
            tenant=TenantContext(
                organization_id,
                organization,
                team_id=None,
                user_id=None,
            ),
            brand_id=brand_row.id,
            brand_slug=cfg.slug,
            brand_context=cfg.understanding,
            routing_config=cfg.routing,
            people_config=cfg.people,
            enabled_sources=enabled_sources,
            max_items_per_source=max_items,
        ),
        memory=memory,
    )
    console.print(
        f"[green]{result.status}[/] processed={result.processed_count} "
        f"skipped={result.skipped_count} synced={result.synced_sources}"
    )
    if result.failed_sources:
        console.print(f"[red]failed_sources={result.failed_sources}[/]")


@app.command("populate-demo-brands")
def populate_demo_brands_cmd(
    organization: str = typer.Option("demo", help="Organization slug to seed/use"),
    brands: list[str] | None = typer.Option(
        None,
        "--brand",
        help="Demo brand to populate. Repeat; defaults to both approved brands.",
    ),
    sources: list[str] | None = typer.Option(
        None,
        "--source",
        help="Public source to populate. Repeat or comma-separate; defaults to reddit.",
    ),
    max_items: int = typer.Option(
        10,
        min=1,
        max=MAX_ITEMS_LIMIT,
        help="Maximum Apify items per source and brand.",
    ),
    dry_run: bool = typer.Option(False, help="Validate and preview without any writes or calls."),
    seed_only: bool = typer.Option(False, help="Write only organization, brand, and profile rows."),
    strict: bool = typer.Option(False, help="Exit non-zero if any selected brand fails."),
    continue_on_error: bool = typer.Option(
        False, help="Continue later brands after failure and return a non-zero status."
    ),
    reliable_classifier: bool = typer.Option(
        False,
        "--reliable-classifier",
        help=(
            "Use Sonnet 5 as classification primary for the Liquid Death/Notion "
            "live fill after GPT-5 Mini fails semantic benchmark gates."
        ),
    ),
) -> None:
    """Seed and populate only the Liquid Death and Notion demo brands.

    Use --reliable-classifier for the live fill when semantic benchmark gates
    require Sonnet 5 as the classification primary.
    """
    _setup_logging()
    requested_brands = brands or list(DEMO_BRANDS)
    invalid = sorted(set(requested_brands) - set(DEMO_BRANDS))
    if invalid:
        raise typer.BadParameter(
            f"Unsupported demo brand(s): {', '.join(invalid)}. "
            f"Choose from: {', '.join(DEMO_BRANDS)}",
            param_hint="--brand",
        )
    if dry_run and seed_only:
        raise typer.BadParameter("--dry-run and --seed-only cannot be combined")
    enabled_sources = _parse_public_sources(sources)
    try:
        summary = populate_demo_brands(
            organization=organization,
            brands=requested_brands,
            sources=enabled_sources,
            max_items=max_items,
            dry_run=dry_run,
            seed_only=seed_only,
            continue_on_error=continue_on_error,
            reliable_classifier=reliable_classifier,
        )
    except (ValueError, FileNotFoundError, DemoPopulationAlreadyRunningError) as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    table = Table(title=f"Demo population ({summary.mode})")
    for column in (
        "brand",
        "sources",
        "processed",
        "skipped",
        "health",
        "volume",
        "relevant",
        "routes",
        "LLM cost",
        "LLM latency",
        "failure",
    ):
        table.add_column(column)
    for item in summary.brands:
        latency = ", ".join(
            f"{stage}:p95={values['p95']:.0f}ms"
            for stage, values in sorted(item.llm_latency_ms.items())
        ) or "-"
        table.add_row(
            item.brand,
            ",".join(item.sources),
            str(item.processed),
            str(item.skipped),
            ", ".join(f"{key}:{value}" for key, value in sorted(item.health.items())) or "-",
            str(item.total_volume),
            str(item.relevant_count),
            str(item.route_count),
            f"${item.llm_cost_usd:.4f}",
            latency,
            item.failure_reason or "-",
        )
    console.print(table)
    if not summary.succeeded and (strict or continue_on_error):
        raise typer.Exit(code=1)


@app.command("worker")
def worker() -> None:
    """Launch Temporal workers for durable ingestion and agent jobs."""
    _setup_logging()
    from resound.workers import run_worker
    from resound.workflows import WorkflowRuntimeConfig

    config = WorkflowRuntimeConfig.from_env()
    console.print(
        "[bold cyan]Launching Resound worker[/] "
        f"task_queue={config.task_queue} namespace={config.namespace} "
        f"address={config.address}"
    )
    asyncio.run(run_worker(config))


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


def _parse_public_sources(values: list[str] | None) -> list[SourceType]:
    raw_values = values or ["reddit"]
    requested = [
        source.strip()
        for value in raw_values
        for source in value.split(",")
        if source.strip()
    ]
    invalid = sorted(set(requested) - V1_PUBLIC_SOURCE_TYPES)
    if invalid:
        allowed = ", ".join(sorted(V1_PUBLIC_SOURCE_TYPES))
        raise typer.BadParameter(
            f"Unsupported source(s): {', '.join(invalid)}. Choose from: {allowed}"
        )
    selected: list[SourceType] = []
    seen: set[str] = set()
    for source in requested:
        if source in seen:
            continue
        selected.append(cast(SourceType, source))
        seen.add(source)
    return selected or [cast(SourceType, "reddit")]


if __name__ == "__main__":
    app()
