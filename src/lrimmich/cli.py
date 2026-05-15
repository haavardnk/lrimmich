from importlib import resources
from pathlib import Path
from typing import Annotated

import typer

import lrimmich
from lrimmich.config import DEFAULT_CONFIG_PATH, load_config

app = typer.Typer(name="lrimmich", no_args_is_help=True)
sync_app = typer.Typer(name="sync", no_args_is_help=True)
config_app = typer.Typer(name="config", no_args_is_help=True)
app.add_typer(sync_app, name="sync")
app.add_typer(config_app, name="config")

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", "-c", help="Config file path."),
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Preview without changes.")
]
JsonOption = Annotated[bool, typer.Option("--json", help="Output as JSON.")]
VerboseOption = Annotated[
    int, typer.Option("--verbose", "-v", count=True, help="Increase verbosity.")
]
QuietOption = Annotated[bool, typer.Option("--quiet", "-q", help="Suppress output.")]
ForceOption = Annotated[bool, typer.Option("--force", help="Skip safety guards.")]
NoDeleteOption = Annotated[bool, typer.Option("--no-delete", help="Skip all deletes.")]


@sync_app.command("all")
def sync_all(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
    json_output: JsonOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = False,
    force: ForceOption = False,
    no_delete: NoDeleteOption = False,
) -> None:
    typer.echo("sync: not implemented")
    raise typer.Exit(1)


@sync_app.command()
def albums(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
    force: ForceOption = False,
    no_delete: NoDeleteOption = False,
) -> None:
    typer.echo("sync albums: not implemented")
    raise typer.Exit(1)


@sync_app.command()
def favorites(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    typer.echo("sync favorites: not implemented")
    raise typer.Exit(1)


@sync_app.command()
def ratings(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    typer.echo("sync ratings: not implemented")
    raise typer.Exit(1)


@sync_app.command()
def tags(
    config: ConfigOption = None,
    dry_run: DryRunOption = False,
) -> None:
    typer.echo("sync tags: not implemented")
    raise typer.Exit(1)


@app.command()
def status(
    config: ConfigOption = None,
    json_output: JsonOption = False,
    verbose: VerboseOption = 0,
    quiet: QuietOption = False,
) -> None:
    typer.echo("status: not implemented")
    raise typer.Exit(1)


@app.command()
def resolve(
    config: ConfigOption = None,
) -> None:
    typer.echo("resolve: not implemented")
    raise typer.Exit(1)


@app.command()
def doctor(
    config: ConfigOption = None,
) -> None:
    from lrimmich.doctor import run_doctor
    from lrimmich.immich import ImmichClient
    from lrimmich.state import StateDB

    cfg = load_config(config)
    client = ImmichClient(cfg.immich_url, cfg.api_key)
    state = StateDB()
    report = run_doctor(cfg, client, state)
    for check in report.checks:
        status = "OK" if check.ok else "FAIL"
        typer.echo(f"[{status}] {check.name}: {check.message}")
    state.close()
    client.close()
    if not report.all_ok:
        raise typer.Exit(1)


@app.command()
def adopt(
    config: ConfigOption = None,
    apply: Annotated[bool, typer.Option("--apply", help="Commit adoption.")] = False,
) -> None:
    from lrimmich.adopt import apply_adopt, find_adopt_candidates
    from lrimmich.catalog import read_collections
    from lrimmich.immich import ImmichClient
    from lrimmich.state import StateDB

    cfg = load_config(config)
    client = ImmichClient(cfg.immich_url, cfg.api_key)
    state = StateDB()
    collections = read_collections(cfg.catalog, cfg.exclude)
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
    redacted["api_key"] = "***"
    for key, value in redacted.items():
        typer.echo(f"{key}: {value}")
