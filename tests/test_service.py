import re
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from lrimmich.cli import app
from lrimmich.service import generate_service, service_paths

runner = CliRunner()


def test_generate_launchd_plist() -> None:
    with patch("lrimmich.service.platform.system", return_value="Darwin"):
        kind, files = generate_service(interval=600)
    assert kind == "launchd"
    assert len(files) == 1
    path = next(iter(files))
    assert "LaunchAgents" in path
    content = next(iter(files.values()))
    assert "<integer>600</integer>" in content
    assert "lrimmich" in content
    assert "sync" in content


def test_generate_systemd_unit() -> None:
    with patch("lrimmich.service.platform.system", return_value="Linux"):
        kind, files = generate_service(interval=300)
    assert kind == "systemd"
    assert len(files) == 2
    paths = list(files.keys())
    assert any("lrimmich.service" in p for p in paths)
    assert any("lrimmich.timer" in p for p in paths)
    service = next(v for k, v in files.items() if "service" in k)
    assert "ExecStart=" in service
    timer = next(v for k, v in files.items() if "timer" in k)
    assert "OnUnitActiveSec=300" in timer


def test_install_service_dry_run() -> None:
    result = runner.invoke(app, ["install-service", "--dry-run"])
    assert result.exit_code == 0
    assert "Would write" in result.output


def test_install_service_help() -> None:
    result = runner.invoke(app, ["install-service", "--help"])
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert "--interval" in plain


def test_service_paths_darwin() -> None:
    with patch("lrimmich.service.platform.system", return_value="Darwin"):
        kind, paths = service_paths()
    assert kind == "launchd"
    assert len(paths) == 1
    assert "LaunchAgents" in str(paths[0])


def test_service_paths_linux() -> None:
    with patch("lrimmich.service.platform.system", return_value="Linux"):
        kind, paths = service_paths()
    assert kind == "systemd"
    assert len(paths) == 2


def test_uninstall_service_dry_run(tmp_path: Path) -> None:
    fake_plist = tmp_path / "com.lrimmich.sync.plist"
    fake_plist.write_text("x")
    with patch("lrimmich.cli.service_paths", return_value=("launchd", [fake_plist])):
        result = runner.invoke(app, ["uninstall-service", "--dry-run"])
    assert result.exit_code == 0
    assert "Would remove" in result.output
    assert fake_plist.exists()


def test_uninstall_service_removes_files(tmp_path: Path) -> None:
    fake_plist = tmp_path / "com.lrimmich.sync.plist"
    fake_plist.write_text("x")
    with patch("lrimmich.cli.service_paths", return_value=("launchd", [fake_plist])):
        result = runner.invoke(app, ["uninstall-service"])
    assert result.exit_code == 0
    assert "Removed" in result.output
    assert not fake_plist.exists()


def test_uninstall_service_no_files() -> None:
    with patch(
        "lrimmich.cli.service_paths",
        return_value=("launchd", [Path("/nonexistent/file.plist")]),
    ):
        result = runner.invoke(app, ["uninstall-service"])
    assert result.exit_code == 0
    assert "No service files found" in result.output
