import asyncio
import logging
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
)

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.orchestrator import run_sync
from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.config import Config, SyncConfig, load_config


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"lrimmich {version('lrimmich')}")
        raise typer.Exit()


app = typer.Typer(
    name="lrimmich",
    no_args_is_help=True,
    callback=lambda version: None,
)


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


config_app = typer.Typer(name="config", no_args_is_help=True)
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


def print_summary(summary: SyncSummary, sync: SyncConfig) -> None:
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
    if sync.captions:
        typer.echo(f"captions: +{summary.captions.set} -{summary.captions.cleared}")
    if sync.stacks:
        typer.echo(
            f"stacks: +{summary.stacks.created} "
            f"~{summary.stacks.updated} "
            f"-{summary.stacks.deleted}"
        )


async def _run_with_progress(
    cfg_path: Path | None,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    quiet: bool = False,
    json_output: bool = False,
    refresh_cache: bool = False,
) -> tuple[SyncSummary, Config]:
    cfg = load_config(cfg_path)
    async with ImmichClient(cfg.immich.url, cfg.immich.api_key) as client:
        state = StateDB()
        try:
            show_progress = not quiet and not json_output
            status_progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                transient=True,
                disable=not show_progress,
            )
            resolve_progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeRemainingColumn(),
                transient=True,
                disable=not show_progress,
            )
            with status_progress, resolve_progress:
                status_task = status_progress.add_task("Starting...", total=None)
                resolve_task: TaskID | None = None

                def on_status(msg: str) -> None:
                    status_progress.update(status_task, description=msg)

                def on_progress(current: int, total: int) -> None:
                    nonlocal resolve_task
                    if resolve_task is None:
                        resolve_task = resolve_progress.add_task(
                            "Resolving paths...", total=total
                        )
                    resolve_progress.update(
                        resolve_task, completed=current, total=total
                    )

                summary = await run_sync(
                    cfg,
                    client,
                    state,
                    dry_run=dry_run,
                    force=force,
                    no_delete=no_delete,
                    on_status=on_status,
                    on_progress=on_progress,
                    refresh_cache=refresh_cache,
                )
        finally:
            state.close()
    return summary, cfg


def run_with_progress(
    cfg_path: Path | None,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    quiet: bool = False,
    json_output: bool = False,
    refresh_cache: bool = False,
) -> tuple[SyncSummary, Config]:
    return asyncio.run(
        _run_with_progress(
            cfg_path, dry_run, force, no_delete, quiet, json_output, refresh_cache
        )
    )
