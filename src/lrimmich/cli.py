import json
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

import lrimmich
from lrimmich.adopt import apply_adopt, find_adopt_candidates
from lrimmich.catalog import read_collections
from lrimmich.config import DEFAULT_CONFIG_PATH, SyncConfig, load_config
from lrimmich.doctor import run_doctor
from lrimmich.immich import ImmichClient
from lrimmich.orchestrator import SyncSummary, run_sync
from lrimmich.state import StateDB

app = typer.Typer(name="lrimmich", no_args_is_help=True)
sync_app = typer.Typer(name="sync", no_args_is_help=True)
config_app = typer.Typer(name="config", no_args_is_help=True)
app.add_typer(sync_app, name="sync")
app.add_typer(config_app, name="config")

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Config file path."),
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Preview without changes.")
]
JsonOption = Annotated[bool, typer.Option("--json", help="Output as JSON.")]
QuietOption = Annotated[bool, typer.Option("--quiet", "-q", help="Suppress output.")]
ForceOption = Annotated[bool, typer.Option("--force", help="Skip safety guards.")]
NoDeleteOption = Annotated[bool, typer.Option("--no-delete", help="Skip all deletes.")]


def _print_summary(summary: SyncSummary, sync: SyncConfig) -> None:
    typer.echo(
        f"albums: +{summary.albums_created} "
        f"~{summary.albums_renamed} "
        f"-{summary.albums_deleted}"
    )
    typer.echo(f"assets: +{summary.assets_added} -{summary.assets_removed}")
    if sync.albums:
        typer.echo(f"covers: +{summary.covers.set} -{summary.covers.cleared}")
    if sync.favorites:
        typer.echo(
            f"favorites: +{summary.favorites.favorited} "
            f"-{summary.favorites.unfavorited}"
        )
    if sync.ratings:
        typer.echo(f"ratings: +{summary.ratings.set} -{summary.ratings.cleared}")
    if sync.rejects:
        typer.echo(
            f"rejects: +{summary.rejects.archived} -{summary.rejects.unarchived}"
        )
    if sync.tags:
        typer.echo(
            f"color_labels: +{summary.color_labels.tagged} "
            f"-{summary.color_labels.untagged}"
        )
        typer.echo(f"keywords: +{summary.keywords.tagged} -{summary.keywords.untagged}")


@sync_app.command("all")
def sync_all(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
    json_output: JsonOption = False,
    quiet: QuietOption = False,
    force: ForceOption = False,
    no_delete: NoDeleteOption = False,
) -> None:
    cfg = load_config(config)
    client = ImmichClient(cfg.immich.url, cfg.immich.api_key)
    state = StateDB()
    show_progress = not quiet and not json_output
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        disable=not show_progress,
    ) as progress:
        task = progress.add_task("Starting...", total=None)

        def on_status(msg: str) -> None:
            progress.update(task, description=msg)

        def on_progress(current: int, total: int) -> None:
            progress.update(task, description=f"Resolving paths... {current}/{total}")

        summary = run_sync(
            cfg,
            client,
            state,
            dry_run=dry_run,
            force=force,
            no_delete=no_delete,
            on_status=on_status,
            on_progress=on_progress,
        )
    if json_output:
        typer.echo(json.dumps(summary.to_dict(), indent=2))
    elif not quiet:
        if dry_run:
            typer.echo("[dry-run] No changes applied")
        _print_summary(summary, cfg.sync)
        for err in summary.errors:
            typer.echo(f"ERROR: {err}", err=True)
    state.close()
    client.close()
    if summary.errors:
        raise typer.Exit(1)


@app.command()
def status(
    config: ConfigOption = None,
    json_output: JsonOption = False,
    quiet: QuietOption = False,
) -> None:
    cfg = load_config(config)
    client = ImmichClient(cfg.immich.url, cfg.immich.api_key)
    state = StateDB()
    show_progress = not quiet and not json_output
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        disable=not show_progress,
    ) as progress:
        task = progress.add_task("Starting...", total=None)

        def on_status(msg: str) -> None:
            progress.update(task, description=msg)

        def on_progress(current: int, total: int) -> None:
            progress.update(task, description=f"Resolving paths... {current}/{total}")

        summary = run_sync(
            cfg,
            client,
            state,
            dry_run=True,
            on_status=on_status,
            on_progress=on_progress,
        )
    if json_output:
        typer.echo(json.dumps(summary.to_dict(), indent=2))
    elif not quiet:
        if summary.has_drift:
            typer.echo("Drift detected:")
        else:
            typer.echo("No drift")
        _print_summary(summary, cfg.sync)
    state.close()
    client.close()
    if summary.has_drift:
        raise typer.Exit(1)


@app.command()
def resolve(
    config: ConfigOption = None,
) -> None:
    typer.echo("resolve: not implemented")
    raise typer.Exit(1)


@app.command()
def doctor(
    config: ConfigOption = None,
) -> None:
    cfg = load_config(config)
    client = ImmichClient(cfg.immich.url, cfg.immich.api_key)
    state = StateDB()
    report = run_doctor(cfg, client, state)
    for check in report.checks:
        status = "OK" if check.ok else "FAIL"
        typer.echo(f"[{status}] {check.name}: {check.message}")
    state.close()
    client.close()
    if not report.all_ok:
        raise typer.Exit(1)


@app.command()
def adopt(
    config: ConfigOption = None,
    apply: Annotated[bool, typer.Option("--apply", help="Commit adoption.")] = False,
) -> None:
    cfg = load_config(config)
    client = ImmichClient(cfg.immich.url, cfg.immich.api_key)
    state = StateDB()
    collections = read_collections(cfg.lightroom.catalog, cfg.exclude)
    candidates = find_adopt_candidates(collections, client, state)
    for c in candidates:
        tag = " [CONFLICT]" if c.conflict else ""
        typer.echo(f"{c.collection_name} -> {c.immich_album_id}{tag}")
    if not candidates:
        typer.echo("No albums to adopt")
    elif apply:
        adopted = apply_adopt(candidates, state)
        typer.echo(f"Adopted {adopted} albums")
    else:
        typer.echo("Run with --apply to commit")
    state.close()
    client.close()


@config_app.command("init")
def config_init() -> None:
    if DEFAULT_CONFIG_PATH.exists():
        typer.echo(f"Config already exists: {DEFAULT_CONFIG_PATH}")
        raise typer.Exit(1)
    DEFAULT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample = resources.files(lrimmich).joinpath("sample_config.toml").read_text()
    DEFAULT_CONFIG_PATH.write_text(sample)
    typer.echo(f"Created {DEFAULT_CONFIG_PATH}")


@config_app.command("show")
def config_show(
    config: ConfigOption = None,
) -> None:
    cfg = load_config(config)
    redacted = cfg.model_dump()
    redacted["immich"]["api_key"] = "***"
    for key, value in redacted.items():
        typer.echo(f"{key}: {value}")
