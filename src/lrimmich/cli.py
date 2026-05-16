import contextlib
import json
import signal
import time
from collections.abc import Callable
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

import lrimmich
from lrimmich.adopt import apply_adopt, find_adopt_candidates
from lrimmich.catalog import read_collections
from lrimmich.config import DEFAULT_CONFIG_PATH, SyncConfig, load_config
from lrimmich.doctor import DoctorReport, run_doctor
from lrimmich.immich import ImmichClient
from lrimmich.notify import send_notification
from lrimmich.orchestrator import SyncSummary, run_sync
from lrimmich.service import generate_service, service_paths
from lrimmich.state import StateDB

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


@app.command()
def sync(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
    json_output: JsonOption = False,
    quiet: QuietOption = False,
    force: ForceOption = False,
    no_delete: NoDeleteOption = False,
    notify_on_drift: Annotated[
        bool,
        typer.Option("--notify-on-drift", help="Notify only on drift."),
    ] = False,
) -> None:
    cfg = load_config(config)
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
        if json_output:
            typer.echo(json.dumps(summary.to_dict(), indent=2))
        elif not quiet:
            if dry_run:
                typer.echo("[dry-run] No changes applied")
            _print_summary(summary, cfg.sync)
            for err in summary.errors:
                typer.echo(f"ERROR: {err}", err=True)
        if cfg.sync.notify_url and not dry_run:
            send_notification(cfg.sync.notify_url, summary, drift_only=notify_on_drift)
    finally:
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
    summary = SyncSummary()
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
    finally:
        state.close()
        client.close()
    if summary.has_drift or summary.errors:
        raise typer.Exit(1)


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


def _sleep_or_stop(seconds: int, should_stop: Callable[[], bool]) -> None:
    for _ in range(seconds):
        if should_stop():
            return
        time.sleep(1)


@app.command(name="install-service")
def install_service(
    interval: Annotated[int, typer.Option(help="Sync interval in seconds.")] = 300,
    dry_run: DryRunOption = False,
) -> None:
    kind, files = generate_service(interval)
    for path, content in files.items():
        if dry_run:
            typer.echo(f"Would write {path}:")
            typer.echo(content)
        else:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            typer.echo(f"Wrote {path}")
    if not dry_run:
        if kind == "launchd":
            plist = next(iter(files))
            typer.echo(f"Run: launchctl load {plist}")
        else:
            typer.echo(
                "Run: systemctl --user daemon-reload"
                " && systemctl --user enable --now lrimmich.timer"
            )


@app.command(name="uninstall-service")
def uninstall_service(
    dry_run: DryRunOption = False,
) -> None:
    kind, paths = service_paths()
    removed = False
    for path in paths:
        if path.exists():
            if dry_run:
                typer.echo(f"Would remove {path}")
            else:
                path.unlink()
                typer.echo(f"Removed {path}")
            removed = True
    if not removed:
        typer.echo("No service files found.")
        return
    if not dry_run:
        if kind == "launchd":
            typer.echo(f"Run: launchctl unload {paths[0]}")
        else:
            typer.echo(
                "Run: systemctl --user disable --now lrimmich.timer"
                " && systemctl --user daemon-reload"
            )


@app.command()
def doctor(
    config: ConfigOption = None,
) -> None:
    cfg = load_config(config)
    client = ImmichClient(cfg.immich.url, cfg.immich.api_key)
    state = StateDB()
    report = DoctorReport()
    try:
        report = run_doctor(cfg, client, state)
        for check in report.checks:
            check_status = "OK" if check.ok else "FAIL"
            typer.echo(f"[{check_status}] {check.name}: {check.message}")
    finally:
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
    try:
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
    finally:
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
