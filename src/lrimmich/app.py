from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

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
) -> None:
    pass


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


def run_with_progress(
    cfg_path: Path | None,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    quiet: bool = False,
    json_output: bool = False,
) -> tuple[SyncSummary, Config]:
    cfg = load_config(cfg_path)
    client = ImmichClient(cfg.immich.url, cfg.immich.api_key)
    state = StateDB()
    try:
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
                progress.update(
                    task, description=f"Resolving paths... {current}/{total}"
                )

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
    finally:
        state.close()
        client.close()
    return summary, cfg
