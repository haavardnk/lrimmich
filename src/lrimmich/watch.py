import contextlib
import signal
from datetime import datetime
from typing import Annotated

import typer

from lrimmich.app import (
    ConfigOption,
    ForceOption,
    NoDeleteOption,
    QuietOption,
    _print_summary,
    _sleep_or_stop,
    app,
)
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.orchestrator import run_sync
from lrimmich.utils.config import load_config


@app.command()
def watch(
    config: ConfigOption = None,
    quiet: QuietOption = False,
    force: ForceOption = False,
    no_delete: NoDeleteOption = False,
    interval: Annotated[int, typer.Option(help="Poll interval in seconds.")] = 60,
    debounce: Annotated[int, typer.Option(help="Debounce seconds after change.")] = 5,
) -> None:
    cfg = load_config(config)
    catalog_path = cfg.lightroom.catalog
    if not catalog_path.exists():
        typer.echo(f"Catalog not found: {catalog_path}", err=True)
        raise typer.Exit(1)

    stop = False

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal stop
        stop = True

    old_sigint = signal.signal(signal.SIGINT, _handle_signal)
    old_sigterm = signal.signal(signal.SIGTERM, _handle_signal)

    last_mtime = 0.0
    if not quiet:
        typer.echo(
            f"Watching {catalog_path} (interval={interval}s, debounce={debounce}s)"
        )

    def _catalog_mtime() -> float:
        mt = 0.0
        for suffix in ("", "-wal", "-shm"):
            p = catalog_path.with_name(catalog_path.name + suffix)
            with contextlib.suppress(OSError):
                mt = max(mt, p.stat().st_mtime)
        return mt

    def _log(msg: str) -> None:
        if not quiet:
            ts = datetime.now().strftime("%H:%M:%S")
            typer.echo(f"[{ts}] {msg}")

    while not stop:
        current_mtime = _catalog_mtime()

        if current_mtime > last_mtime and last_mtime > 0:
            _sleep_or_stop(debounce, lambda: stop)
            if stop:
                break
            current_mtime = _catalog_mtime()
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
                    _print_summary(summary, cfg.sync)
                    for err in summary.errors:
                        typer.echo(f"ERROR: {err}", err=True)
                _log("Sync complete")
            except Exception as e:
                _log(f"Sync error: {e}")
            finally:
                state.close()
                client.close()

        last_mtime = current_mtime
        _sleep_or_stop(interval, lambda: stop)

    if not quiet:
        typer.echo("Stopped")
    signal.signal(signal.SIGINT, old_sigint)
    signal.signal(signal.SIGTERM, old_sigterm)
