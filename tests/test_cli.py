from importlib import resources
from pathlib import Path

import pytest
from typer.testing import CliRunner

import lrimmich
from lrimmich.cli import app

runner = CliRunner()


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["sync", "--help"],
        ["sync", "all", "--help"],
        ["sync", "albums", "--help"],
        ["sync", "favorites", "--help"],
        ["sync", "ratings", "--help"],
        ["sync", "tags", "--help"],
        ["status", "--help"],
        ["resolve", "--help"],
        ["doctor", "--help"],
        ["adopt", "--help"],
        ["config", "--help"],
        ["config", "init", "--help"],
        ["config", "show", "--help"],
    ],
)
def test_help(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert "Usage" in result.output or "--help" in result.output


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "Usage" in result.output


def test_config_show_redacts_key(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'catalog = "/tmp/test.lrcat"\n'
        'immich_url = "http://localhost"\n'
        'api_key = "secret-key-123"\n'
    )
    result = runner.invoke(app, ["config", "show", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "secret-key-123" not in result.output
    assert "***" in result.output


def test_config_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "lrimmich" / "config.toml"
    monkeypatch.setattr("lrimmich.cli.DEFAULT_CONFIG_PATH", target)
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    assert target.exists()
    expected = resources.files(lrimmich).joinpath("sample_config.toml").read_text()
    assert target.read_text() == expected


def test_config_init_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "config.toml"
    target.write_text("existing")
    monkeypatch.setattr("lrimmich.cli.DEFAULT_CONFIG_PATH", target)
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 1


def test_sync_all_stub() -> None:
    result = runner.invoke(app, ["sync", "all"])
    assert result.exit_code == 1
    assert "not implemented" in result.output


def test_status_stub() -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    assert "not implemented" in result.output


def test_json_flag_accepted() -> None:
    result = runner.invoke(app, ["sync", "all", "--json"])
    assert result.exit_code == 1


def test_dry_run_flag_accepted() -> None:
    result = runner.invoke(app, ["sync", "albums", "--dry-run"])
    assert result.exit_code == 1


def test_force_flag_accepted() -> None:
    result = runner.invoke(app, ["sync", "albums", "--force"])
    assert result.exit_code == 1


def test_no_delete_flag_accepted() -> None:
    result = runner.invoke(app, ["sync", "albums", "--no-delete"])
    assert result.exit_code == 1
