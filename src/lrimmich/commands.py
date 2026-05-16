import json
from importlib import resources
from typing import Annotated

import typer

import lrimmich.utils as lrimmich_utils
from lrimmich.app import (
    ConfigOption,
    DryRunOption,
    ForceOption,
    JsonOption,
    NoDeleteOption,
    QuietOption,
    _print_summary,
    _run_with_progress,
    app,
    config_app,
)
from lrimmich.clients.catalog import read_collections
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.utils.adopt import apply_adopt, find_adopt_candidates
from lrimmich.utils.config import DEFAULT_CONFIG_PATH, load_config
from lrimmich.utils.doctor import DoctorReport, run_doctor
from lrimmich.utils.notify import send_notification


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
    summary, cfg = _run_with_progress(
        config,
        dry_run=dry_run,
        force=force,
        no_delete=no_delete,
        quiet=quiet,
        json_output=json_output,
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
    if summary.errors:
        raise typer.Exit(1)


@app.command()
def status(
    config: ConfigOption = None,
    json_output: JsonOption = False,
    quiet: QuietOption = False,
) -> None:
    summary, cfg = _run_with_progress(
        config, dry_run=True, quiet=quiet, json_output=json_output
    )
    if json_output:
        typer.echo(json.dumps(summary.to_dict(), indent=2))
    elif not quiet:
        if summary.has_drift:
            typer.echo("Drift detected:")
        else:
            typer.echo("No drift")
        _print_summary(summary, cfg.sync)
    if summary.has_drift or summary.errors:
        raise typer.Exit(1)


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
    sample = resources.files(lrimmich_utils).joinpath("sample_config.toml").read_text()
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
