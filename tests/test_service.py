import re
from unittest.mock import patch

from typer.testing import CliRunner

from lrimmich.cli import app
from lrimmich.service import generate_service

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
