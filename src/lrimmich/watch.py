import logging
import threading
from datetime import datetime
from typing import Annotated

import typer
from watchfiles import watch as watch_files

from lrimmich.app import (
    ConfigOption,
    ForceOption,
    NoDeleteOption,
    QuietOption,
    app,
    print_summary,
)
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.orchestrator import run_sync
from lrimmich.utils.config import load_config

logger = logging.getLogger(__name__)


@app.command()
def watch(
    config: ConfigOption = None,
    quiet: QuietOption = False,
    force: ForceOption = False,
    no_delete: NoDeleteOption = False,
    debounce: Annotated[
        int, typer.Option(help="Debounce milliseconds after change.")
    ] = 5000,
) -> None:
    cfg = load_config(config)
    catalog_path = cfg.lightroom.catalog
    if not catalog_path.exists():
        typer.echo(f"Catalog not found: {catalog_path}", err=True)
        raise typer.Exit(1)

    watched = [
        str(catalog_path.with_name(catalog_path.name + suffix))
        for suffix in ("", "-wal", "-shm")
    ]
    stop_event = threading.Event()

    def _log(msg: str) -> None:
        if not quiet:
            ts = datetime.now().strftime("%H:%M:%S")
            typer.echo(f"[{ts}] {msg}")

    if not quiet:
        typer.echo(f"Watching {catalog_path} (debounce={debounce}ms)")

    for _ in watch_files(
        *watched,
        debounce=debounce,
        stop_event=stop_event,
        raise_interrupt=False,
    ):
        _log("Change detected, syncing...")
        client = ImmichClient(cfg.immich.url, cfg.immich.api_key)
        state = StateDB()
        try:
            summary = run_sync(
                cfg,
                client,
                state,
                dry_run=False,
                force=force,
                no_delete=no_delete,
            )
            if not quiet:
                print_summary(summary, cfg.sync)
                for err in summary.errors:
                    typer.echo(f"ERROR: {err}", err=True)
            _log("Sync complete")
        except Exception:
            logger.exception("Sync error")
            _log("Sync failed")
        finally:
            state.close()
            client.close()

    if not quiet:
        typer.echo("Stopped")
