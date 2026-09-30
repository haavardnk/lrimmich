import asyncio
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

MAX_FAILURES: int = 5


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

    missing = [c.catalog for c in cfg.catalogs if not c.catalog.exists()]
    if missing:
        typer.echo(f"Catalog not found: {missing[0]}", err=True)
        raise typer.Exit(1)
    watched = [
        str(c.catalog.with_name(c.catalog.name + suffix))
        for c in cfg.catalogs
        for suffix in ("", "-wal", "-shm")
    ]

    def _log(msg: str) -> None:
        if not quiet:
            ts = datetime.now().strftime("%H:%M:%S")
            typer.echo(f"[{ts}] {msg}")

    if not quiet:
        names = ", ".join(c.catalog.name for c in cfg.catalogs)
        typer.echo(f"Watching {names} (debounce={debounce}ms)")

    failures = 0

    async def _do_sync() -> list[str]:
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
        return summary.errors

    try:
        with asyncio.Runner() as runner:
            for _ in watch_files(
                *watched,
                debounce=debounce,
                raise_interrupt=False,
            ):
                _log("Change detected, syncing...")
                try:
                    errors = runner.run(_do_sync())
                except Exception:
                    logger.exception("sync_error", failure=failures + 1)
                    errors = ["sync crashed"]
                if not errors:
                    _log("Sync complete")
                    failures = 0
                    continue
                failures += 1
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
