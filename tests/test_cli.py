from importlib import resources
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
        ["collections", "--help"],
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


def test_config_edit_opens_editor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[lightroom]\n")
    monkeypatch.setenv("EDITOR", "true")
    monkeypatch.delenv("VISUAL", raising=False)
    result = runner.invoke(app, ["config", "edit", "--config", str(cfg)])
    assert result.exit_code == 0


def test_config_edit_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "edit", "--config", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "not found" in result.output


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "lrimmich" in result.output


def test_log_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lrimmich.commands.DEFAULT_STATE_PATH", tmp_path / "state.db")
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0
    assert "No log entries" in result.output


def test_log_shows_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from lrimmich.clients.state import StateDB

    db_path = tmp_path / "state.db"
    monkeypatch.setattr("lrimmich.commands.DEFAULT_STATE_PATH", db_path)
    state = StateDB(db_path)
    state.append_audit_log("sync_albums", "albums", payload={"created": 3})
    state.close()
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0
    assert "sync_albums" in result.output
    assert "created=3" in result.output


def test_log_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from lrimmich.clients.state import StateDB

    db_path = tmp_path / "state.db"
    monkeypatch.setattr("lrimmich.commands.DEFAULT_STATE_PATH", db_path)
    state = StateDB(db_path)
    state.append_audit_log("sync_albums", "albums")
    state.close()
    result = runner.invoke(app, ["log", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["action"] == "sync_albums"


def test_reset_deletes_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "state.db"
    db_path.write_text("fake")
    monkeypatch.setattr("lrimmich.commands.DEFAULT_STATE_PATH", db_path)
    result = runner.invoke(app, ["reset", "--force"])
    assert result.exit_code == 0
    assert "State cleared" in result.output
    assert not db_path.exists()


def test_reset_no_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("lrimmich.commands.DEFAULT_STATE_PATH", tmp_path / "nope.db")
    result = runner.invoke(app, ["reset", "--force"])
    assert result.exit_code == 0
    assert "No state database" in result.output


def test_reset_prompts_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "state.db"
    db_path.write_text("fake")
    monkeypatch.setattr("lrimmich.commands.DEFAULT_STATE_PATH", db_path)
    runner.invoke(app, ["reset"], input="n\n")
    assert db_path.exists()


def test_collections_tree(tmp_path: Path) -> None:
    from tests.fixtures.catalog_factory import CatalogBuilder

    catalog = tmp_path / "test.lrcat"
    builder = CatalogBuilder(catalog)
    builder.add_set(10, "Travel")
    builder.add_collection(20, "Paris", parent=10)
    builder.add_collection(30, "London", parent=10)
    builder.build()

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[lightroom]\n"
        f'catalog = "{catalog}"\n'
        "[immich]\n"
        'url = "http://localhost"\n'
        'api_key = "k"\n'
        'library_path = "/ext/"\n'
    )
    result = runner.invoke(app, ["collections", "--config", str(cfg)])
    assert result.exit_code == 0
    assert "Travel" in result.output
    assert "Paris" in result.output
    assert "id=10" in result.output
    assert "[set]" in result.output
    assert "[col]" in result.output


def test_collections_json(tmp_path: Path) -> None:
    import json

    from tests.fixtures.catalog_factory import CatalogBuilder

    catalog = tmp_path / "test.lrcat"
    builder = CatalogBuilder(catalog)
    builder.add_set(10, "Travel")
    builder.add_collection(20, "Paris", parent=10)
    builder.build()

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[lightroom]\n"
        f'catalog = "{catalog}"\n'
        "[immich]\n"
        'url = "http://localhost"\n'
        'api_key = "k"\n'
        'library_path = "/ext/"\n'
    )
    result = runner.invoke(app, ["collections", "--json", "--config", str(cfg)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["name"] == "Travel"
    assert data[0]["children"][0]["name"] == "Paris"


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
    mock_client = AsyncMock()
    mock_cls = MagicMock(return_value=mock_client)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("lrimmich.app.run_sync", side_effect=RuntimeError("boom")),
        patch("lrimmich.app.ImmichClient", mock_cls),
        patch("lrimmich.app.StateDB") as mock_state_cls,
    ):
        mock_state = mock_state_cls.return_value
        runner.invoke(app, ["sync", "--config", str(cfg_path)])
        mock_client.__aexit__.assert_called_once()
        mock_state.close.assert_called_once()
