import asyncio
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
    InteractiveOption,
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
from lrimmich.clients.state import DEFAULT_STATE_DIR, StateDB, state_path_for_catalog
from lrimmich.utils.adopt import apply_adopt, find_adopt_candidates
from lrimmich.utils.config import DEFAULT_CONFIG_PATH, load_config
from lrimmich.utils.doctor import DoctorReport, run_doctor
from lrimmich.utils.notify import send_notification


@app.command()
def sync(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
    force: ForceOption = False,
    interactive: InteractiveOption = False,
    json_output: JsonOption = False,
    no_delete: NoDeleteOption = False,
    notify_on_drift: Annotated[
        bool,
        typer.Option("--notify-on-drift", help="Notify only on drift."),
    ] = False,
    quiet: QuietOption = False,
    refresh_cache: Annotated[
        bool,
        typer.Option("--refresh-cache", help="Ignore cached path resolutions."),
    ] = False,
) -> None:
    summary, cfg = run_with_progress(
        config,
        dry_run=dry_run,
        force=force,
        interactive=interactive,
        json_output=json_output,
        no_delete=no_delete,
        quiet=quiet,
        refresh_cache=refresh_cache,
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
    refresh_cache: Annotated[
        bool,
        typer.Option("--refresh-cache", help="Ignore cached path resolutions."),
    ] = False,
) -> None:
    summary, cfg = run_with_progress(
        config,
        dry_run=True,
        quiet=quiet,
        json_output=json_output,
        refresh_cache=refresh_cache,
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
    async def _run() -> DoctorReport:
        cfg = load_config(config)
        async with ImmichClient(cfg.immich.url, cfg.immich.api_key) as client:
            config_path = config or DEFAULT_CONFIG_PATH
            return await run_doctor(cfg, client, config_path=config_path)

    report = asyncio.run(_run())
    for check in report.checks:
        check_status = "OK" if check.ok else "FAIL"
        typer.echo(f"[{check_status}] {check.name}: {check.message}")
    if not report.all_ok:
        raise typer.Exit(1)


@app.command()
def adopt(
    config: ConfigOption = None,
    apply: Annotated[bool, typer.Option("--apply", help="Commit adoption.")] = False,
) -> None:
    async def _run() -> tuple[list, list[StateDB]]:
        cfg = load_config(config)
        all_candidates: list = []
        states: list[StateDB] = []
        async with ImmichClient(cfg.immich.url, cfg.immich.api_key) as client:
            for catalog in cfg.catalogs:
                state = StateDB(state_path_for_catalog(catalog.key))
                states.append(state)
                try:
                    collections = read_collections(catalog.catalog, catalog)
                    candidates = await find_adopt_candidates(collections, client, state)
                    all_candidates.extend(candidates)
                except Exception:
                    for s in states:
                        s.close()
                    raise
        return all_candidates, states

    candidates, states = asyncio.run(_run())
    try:
        for c in candidates:
            tag = " [CONFLICT]" if c.conflict else ""
            typer.echo(f"{c.collection_name} -> {c.immich_album_id}{tag}")
        if not candidates:
            typer.echo("No albums to adopt")
        elif apply:
            total = 0
            for state in states:
                total += apply_adopt(candidates, state)
            typer.echo(f"Adopted {total} albums")
        else:
            typer.echo("Run with --apply to commit")
    finally:
        for state in states:
            state.close()


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
    all_entries: list[dict] = []
    for db_path in DEFAULT_STATE_DIR.glob("state*.db"):
        state = StateDB(db_path)
        try:
            all_entries.extend(state.get_audit_log(limit=limit))
        finally:
            state.close()
    all_entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    entries = all_entries[:limit]
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
    state_files = list(DEFAULT_STATE_DIR.glob("state*.db"))
    if not state_files:
        typer.echo("No state databases found.")
        return
    if not force:
        typer.confirm(
            f"Delete {len(state_files)} state database(s)?"
            " Next sync will rebuild from scratch.",
            abort=True,
        )
    for f in state_files:
        f.unlink()
    typer.echo("State cleared.")


@app.command()
def collections(
    config: ConfigOption = None,
    json_output: JsonOption = False,
) -> None:
    cfg = load_config(config)
    from lrimmich.clients.catalog import LrCollectionTreeNode

    all_nodes: list[dict] = []
    for catalog in cfg.catalogs:
        tree = read_collection_tree(catalog.catalog)
        if json_output:
            all_nodes.extend(n.model_dump() for n in tree)
        else:
            if len(cfg.catalogs) > 1:
                typer.echo(f"\n{catalog.catalog.name}:")

            def _print_tree(nodes: list[LrCollectionTreeNode], indent: int = 0) -> None:
                for node in nodes:
                    pfx = "  " * indent
                    label = "set" if node.kind == "set" else "col"
                    typer.echo(f"{pfx}[{label}] {node.name}  (id={node.id})")
                    _print_tree(node.children, indent + 1)

            _print_tree(tree)
    if json_output:
        typer.echo(json.dumps(all_nodes, indent=2))


@app.command()
def docs() -> None:
    from lrimmich import DOCS_URL

    typer.launch(DOCS_URL)
