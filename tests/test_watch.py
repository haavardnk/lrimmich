import re
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from lrimmich.app import app

runner = CliRunner()


def test_watch_missing_catalog(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[lightroom]\ncatalog = "{tmp_path / "missing.lrcat"}"\n'
        '[immich]\nurl = "http://test"\napi_key = "k"\nlibrary_path = "/img"\n'
    )
    result = runner.invoke(app, ["watch", "--config", str(config_path)])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_watch_runs_sync_on_change(tmp_path: Path) -> None:
    catalog = tmp_path / "test.lrcat"
    catalog.write_text("x")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[lightroom]\ncatalog = "{catalog}"\n'
        '[immich]\nurl = "http://test"\napi_key = "k"\nlibrary_path = "/img"\n'
    )
    fake_changes = iter([{("modified", str(catalog))}])
    with (
        patch("lrimmich.watch.watch_files", return_value=fake_changes),
        patch("lrimmich.watch.run_sync") as mock_sync,
        patch("lrimmich.watch.ImmichClient"),
        patch("lrimmich.watch.StateDB"),
    ):
        mock_sync.return_value.errors = []
        result = runner.invoke(app, ["watch", "--config", str(config_path)])
        assert result.exit_code == 0
        mock_sync.assert_called_once()


def test_watch_help_shows_options() -> None:
    result = runner.invoke(app, ["watch", "--help"])
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--debounce" in plain
