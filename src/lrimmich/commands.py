import json
import os
import platform
import subprocess
from datetime import UTC
from importlib import resources
from typing import Annotated

import tomli_w
import typer

import lrimmich.utils as lrimmich_utils
from lrimmich.app import (
    ConfigOption,
    DryRunOption,
    ForceOption,
    JsonOption,
    NoDeleteOption,
    QuietOption,
    app,
    config_app,
    print_summary,
    run_with_progress,
)
from lrimmich.clients.catalog import read_collection_tree, read_collections
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import DEFAULT_STATE_PATH, StateDB
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
    summary, cfg = run_with_progress(
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
        print_summary(summary, cfg.sync)
        for err in summary.errors:
            typer.echo(f"ERROR: {err}", err=True)
    if cfg.notification.url and not dry_run:
        send_notification(cfg.notification.url, summary, drift_only=notify_on_drift)
    if summary.errors:
        raise typer.Exit(1)


@app.command()
def status(
    config: ConfigOption = None,
    json_output: JsonOption = False,
    quiet: QuietOption = False,
) -> None:
    summary, cfg = run_with_progress(
        config, dry_run=True, quiet=quiet, json_output=json_output
    )
    if json_output:
        typer.echo(json.dumps(summary.to_dict(), indent=2))
    elif not quiet:
        if summary.has_drift:
            typer.echo("Drift detected:")
        else:
            typer.echo("No drift")
        print_summary(summary, cfg.sync)
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
        config_path = config or DEFAULT_CONFIG_PATH
        report = run_doctor(cfg, client, state, config_path=config_path)
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
    data = cfg.model_dump(mode="json")
    data["immich"]["api_key"] = "***"
    typer.echo(tomli_w.dumps(data))


@config_app.command("edit")
def config_edit(config: ConfigOption = None) -> None:
    path = config or DEFAULT_CONFIG_PATH
    if not path.exists():
        typer.echo(f"Config not found: {path}\nRun 'lrimmich config init' first.")
        raise typer.Exit(1)
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if editor:
        subprocess.call([editor, str(path)])
    elif platform.system() == "Darwin":
        subprocess.call(["open", str(path)])
    else:
        subprocess.call(["xdg-open", str(path)])


@app.command()
def log(
    limit: Annotated[int, typer.Option("--limit", "-n")] = 20,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    state = StateDB(DEFAULT_STATE_PATH)
    try:
        entries = state.get_audit_log(limit=limit)
    finally:
        state.close()
    if not entries:
        typer.echo("No log entries.")
        return
    if json_output:
        typer.echo(json.dumps(entries, indent=2))
        return
    from datetime import datetime

    for e in reversed(entries):
        ts = datetime.fromtimestamp(e["ts"], tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        payload = json.loads(e["payload_json"]) if e.get("payload_json") else {}
        detail = " ".join(f"{k}={v}" for k, v in payload.items())
        typer.echo(f"{ts}  {e['action']:<25} {detail}")


@app.command()
def reset(
    force: Annotated[bool, typer.Option("--force", "-f")] = False,
) -> None:
    if not DEFAULT_STATE_PATH.exists():
        typer.echo("No state database found.")
        return
    if not force:
        typer.confirm(
            f"Delete {DEFAULT_STATE_PATH}? Next sync will rebuild from scratch.",
            abort=True,
        )
    DEFAULT_STATE_PATH.unlink()
    typer.echo("State cleared.")


@app.command()
def collections(
    config: ConfigOption = None,
    json_output: JsonOption = False,
) -> None:
    cfg = load_config(config)
    tree = read_collection_tree(cfg.lightroom.catalog)
    if json_output:
        typer.echo(json.dumps([n.model_dump() for n in tree], indent=2))
        return
    from lrimmich.clients.catalog import LrCollectionTreeNode

    def _print_tree(nodes: list[LrCollectionTreeNode], indent: int = 0) -> None:
        for node in nodes:
            prefix = "  " * indent
            label = "set" if node.kind == "set" else "col"
            typer.echo(f"{prefix}[{label}] {node.name}  (id={node.id})")
            _print_tree(node.children, indent + 1)

    _print_tree(tree)
