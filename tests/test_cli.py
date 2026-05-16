from importlib import resources
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

import lrimmich.utils as lrimmich_utils
from lrimmich.app import app
from lrimmich.sync.summary import SyncSummary

runner = CliRunner()


@pytest.mark.parametrize(
    "args",
    [
        ["--help"],
        ["sync", "--help"],
        ["status", "--help"],
        ["watch", "--help"],
        ["install-service", "--help"],
        ["uninstall-service", "--help"],
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
        "[lightroom]\n"
        'catalog = "/tmp/test.lrcat"\n'
        "[immich]\n"
        'url = "http://localhost"\n'
        'api_key = "secret-key-123"\n'
        'library_path = "/ext/"\n'
    )
    result = runner.invoke(app, ["config", "show", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "secret-key-123" not in result.output
    assert "***" in result.output


def test_config_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "lrimmich" / "config.toml"
    monkeypatch.setattr("lrimmich.commands.DEFAULT_CONFIG_PATH", target)
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    assert target.exists()
    sample = resources.files(lrimmich_utils).joinpath("sample_config.toml")
    expected = sample.read_text()
    assert target.read_text() == expected


def test_config_init_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "config.toml"
    target.write_text("existing")
    monkeypatch.setattr("lrimmich.commands.DEFAULT_CONFIG_PATH", target)
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 1


def test_status_exits_nonzero_on_errors(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "[lightroom]\n"
        f'catalog = "{tmp_path / "test.lrcat"}"\n'
        "[immich]\n"
        'url = "http://localhost"\n'
        'api_key = "k"\n'
        'library_path = "/ext/"\n'
    )
    summary = SyncSummary()
    summary.errors.append("some error")
    with patch("lrimmich.app.run_sync", return_value=summary):
        result = runner.invoke(app, ["status", "--config", str(cfg_path), "-q"])
    assert result.exit_code == 1


def test_sync_closes_client_on_exception(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "[lightroom]\n"
        f'catalog = "{tmp_path / "test.lrcat"}"\n'
        "[immich]\n"
        'url = "http://localhost"\n'
        'api_key = "k"\n'
        'library_path = "/ext/"\n'
    )
    with (
        patch("lrimmich.app.run_sync", side_effect=RuntimeError("boom")),
        patch("lrimmich.app.ImmichClient") as mock_cls,
        patch("lrimmich.app.StateDB") as mock_state_cls,
    ):
        mock_client = mock_cls.return_value
        mock_state = mock_state_cls.return_value
        runner.invoke(app, ["sync", "--config", str(cfg_path)])
        mock_client.close.assert_called_once()
        mock_state.close.assert_called_once()
