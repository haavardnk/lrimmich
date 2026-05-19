import asyncio
import threading
from datetime import datetime
from typing import Annotated

import structlog
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
from lrimmich.sync.orchestrator import run_multi_sync
from lrimmich.utils.config import load_config

logger = structlog.get_logger(__name__)


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

    watched: list[str] = []
    for catalog in cfg.catalogs:
        if not catalog.catalog.exists():
            typer.echo(f"Catalog not found: {catalog.catalog}", err=True)
            raise typer.Exit(1)
        for suffix in ("", "-wal", "-shm"):
            watched.append(
                str(catalog.catalog.with_name(catalog.catalog.name + suffix))
            )

    stop_event = threading.Event()

    def _log(msg: str) -> None:
        if not quiet:
            ts = datetime.now().strftime("%H:%M:%S")
            typer.echo(f"[{ts}] {msg}")

    if not quiet:
        names = ", ".join(c.catalog.name for c in cfg.catalogs)
        typer.echo(f"Watching {names} (debounce={debounce}ms)")

    failures = 0
    MAX_FAILURES = 5

    async def _do_sync() -> None:
        async with ImmichClient(cfg.immich.url, cfg.immich.api_key) as client:
            summary = await run_multi_sync(
                cfg,
                client,
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
                logger.exception(
                    "sync_error", failure=failures, max_failures=MAX_FAILURES
                )
                _log(f"Sync failed ({failures}/{MAX_FAILURES})")
                if failures >= MAX_FAILURES:
                    typer.echo(
                        f"Aborting watch after {MAX_FAILURES} consecutive failures",
                        err=True,
                    )
                    raise typer.Exit(1) from None
    except KeyboardInterrupt:
        pass

    if not quiet:
        typer.echo("Stopped")
