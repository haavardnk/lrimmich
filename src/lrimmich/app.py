from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.config import SyncConfig

app = typer.Typer(name="lrimmich", no_args_is_help=True)
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


def _sleep_or_stop(seconds: int, should_stop: Callable[[], bool]) -> None:
    import time

    for _ in range(seconds):
        if should_stop():
            return
        time.sleep(1)
