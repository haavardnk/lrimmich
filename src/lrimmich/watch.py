import asyncio
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

    state = StateDB()
    failures = 0
    MAX_FAILURES = 5

    async def _do_sync() -> None:
        async with ImmichClient(cfg.immich.url, cfg.immich.api_key) as client:
            summary = await run_sync(
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

    try:
        for _ in watch_files(
            *watched,
            debounce=debounce,
            stop_event=stop_event,
            raise_interrupt=False,
        ):
            _log("Change detected, syncing...")
            try:
                asyncio.run(_do_sync())
                _log("Sync complete")
                failures = 0
            except Exception:
                failures += 1
                logger.exception("Sync error (failure %d/%d)", failures, MAX_FAILURES)
                _log(f"Sync failed ({failures}/{MAX_FAILURES})")
                if failures >= MAX_FAILURES:
                    typer.echo(
                        f"Aborting watch after {MAX_FAILURES} consecutive failures",
                        err=True,
                    )
                    raise typer.Exit(1) from None
                state.close()
                state = StateDB()
    finally:
        state.close()

    if not quiet:
        typer.echo("Stopped")
