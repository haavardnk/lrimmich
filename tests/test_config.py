from pathlib import Path

import pytest
from pydantic import ValidationError

from lrimmich.config import load_config

MINIMAL_TOML = """\
catalog = "/tmp/test.lrcat"
immich_url = "http://localhost:2283"
api_key = "testkey123456"

[[path_map]]
lr_path = "/lr/"
immich_path = "/immich/"
"""

ENV_KEY_TOML = """\
catalog = "/tmp/test.lrcat"
immich_url = "http://localhost:2283"
api_key_env = "MY_TEST_KEY"
"""


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)
    return p


def test_load_basic(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert cfg.catalog == Path("/tmp/test.lrcat")
    assert cfg.immich_url == "http://localhost:2283"
    assert cfg.api_key == "testkey123456"
    assert len(cfg.path_map) == 1
    assert cfg.path_map[0].lr_path == "/lr/"


def test_missing_api_key(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
catalog = "/tmp/test.lrcat"
immich_url = "http://localhost:2283"
""")
    with pytest.raises(ValidationError, match="api_key"):
        load_config(p)


def test_missing_config_file() -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        load_config(Path("/nonexistent/config.toml"))


def test_missing_required_field(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
catalog = "/tmp/test.lrcat"
api_key = "k123456"
""")
    with pytest.raises(ValidationError, match="immich_url"):
        load_config(p)


def test_defaults(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert cfg.sync.albums is True
    assert cfg.sync.ratings is True
    assert cfg.favorites.scope == "collections"
    assert cfg.safety.delete_threshold == 100


def test_invalid_favorites_scope(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
catalog = "/tmp/test.lrcat"
immich_url = "http://localhost:2283"
api_key = "testkey123456"

[favorites]
scope = "invalid"
""")
    with pytest.raises(ValidationError):
        load_config(p)


def test_extra_field_rejected(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
catalog = "/tmp/test.lrcat"
immich_url = "http://localhost:2283"
api_key = "testkey123456"
bogus_field = "should fail"
""")
    with pytest.raises(ValidationError):
        load_config(p)
