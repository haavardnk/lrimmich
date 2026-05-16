import re
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from lrimmich.app import _sleep_or_stop, app

runner = CliRunner()


def test_sleep_or_stop_exits_early() -> None:
    called = False

    def should_stop() -> bool:
        nonlocal called
        if called:
            return True
        called = True
        return False

    _sleep_or_stop(100, should_stop)
    assert called


def test_sleep_or_stop_runs_full() -> None:
    _sleep_or_stop(0, lambda: False)


def test_watch_missing_catalog(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[lightroom]\ncatalog = "{tmp_path / "missing.lrcat"}"\n'
        '[immich]\nurl = "http://test"\napi_key = "k"\nlibrary_path = "/img"\n'
    )
    result = runner.invoke(app, ["watch", "--config", str(config_path)])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_watch_no_work_when_mtime_unchanged(tmp_path: Path) -> None:
    catalog = tmp_path / "test.lrcat"
    catalog.write_text("x")
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f'[lightroom]\ncatalog = "{catalog}"\n'
        '[immich]\nurl = "http://test"\napi_key = "k"\nlibrary_path = "/img"\n'
    )
    call_count = 0

    def fake_sleep(seconds: int, should_stop: callable) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise SystemExit(0)

    with (
        patch("lrimmich.watch._sleep_or_stop", side_effect=fake_sleep),
        patch("lrimmich.watch.run_sync") as mock_sync,
    ):
        runner.invoke(app, ["watch", "--config", str(config_path), "--interval", "1"])
        mock_sync.assert_not_called()


def test_watch_help_shows_options() -> None:
    result = runner.invoke(app, ["watch", "--help"])
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--interval" in plain
    assert "--debounce" in plain
