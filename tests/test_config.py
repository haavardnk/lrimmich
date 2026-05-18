from pathlib import Path

import pytest
from pydantic import ValidationError

from lrimmich.utils.config import load_config

MINIMAL_TOML = """\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_path = "/immich/"
"""


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)
    return p


def test_load_basic(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert cfg.lightroom.catalog == Path("/tmp/test.lrcat")
    assert cfg.immich.url == "http://localhost:2283"
    assert cfg.immich.api_key == "testkey123456"
    assert cfg.immich.library_path == "/immich/"


def test_missing_api_key(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
library_path = "/immich/"
""")
    with pytest.raises(SystemExit, match="api_key"):
        load_config(p)


def test_api_key_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
library_path = "/immich/"
""")
    monkeypatch.setenv("LRIMMICH_API_KEY", "from-env")
    cfg = load_config(p)
    assert cfg.immich.api_key == "from-env"


def test_missing_config_file() -> None:
    with pytest.raises(SystemExit, match="config init"):
        load_config(Path("/nonexistent/config.toml"))


def test_missing_required_field(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
api_key = "k123456"
library_path = "/immich/"
""")
    with pytest.raises(ValidationError, match="url"):
        load_config(p)


def test_defaults(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert cfg.sync.albums is True
    assert cfg.sync.ratings is True
    assert cfg.sync.scope == "collections"
    assert cfg.safety.delete_threshold == 100


def test_invalid_sync_scope(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_path = "/immich/"

[sync]
scope = "invalid"
""")
    with pytest.raises(ValidationError):
        load_config(p)


def test_extra_field_ignored(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_path = "/immich/"
bogus_field = "should be ignored"
""")
    cfg = load_config(p)
    assert cfg.immich.url == "http://localhost:2283"
    assert not hasattr(cfg.immich, "bogus_field")


def test_album_mode_default(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert cfg.sync.album_mode == "managed"


def test_album_mode_hybrid(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_path = "/immich/"

[sync]
album_mode = "hybrid"
""")
    cfg = load_config(p)
    assert cfg.sync.album_mode == "hybrid"


def test_album_mode_invalid(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[lightroom]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_path = "/immich/"

[sync]
album_mode = "bogus"
""")
    with pytest.raises(ValidationError):
        load_config(p)
