from pathlib import Path

import pytest
from pydantic import ValidationError

from lrimmich.utils.config import load_config

MINIMAL_TOML = """\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]
"""


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(MINIMAL_TOML)
    return p


def test_load_basic(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert cfg.catalogs[0].catalog == Path("/tmp/test.lrcat")
    assert cfg.immich.url == "http://localhost:2283"
    assert cfg.immich.api_key == "testkey123456"
    assert cfg.immich.library_paths == ["/immich/"]


def test_missing_api_key(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
library_paths = ["/immich/"]
""")
    with pytest.raises(SystemExit, match="api_key"):
        load_config(p)


def test_api_key_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
library_paths = ["/immich/"]
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
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
api_key = "k123456"
library_paths = ["/immich/"]
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
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]

[sync]
scope = "invalid"
""")
    with pytest.raises(ValidationError):
        load_config(p)


def test_extra_field_ignored(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]
bogus_field = "should be ignored"
""")
    cfg = load_config(p)
    assert cfg.immich.url == "http://localhost:2283"
    assert not hasattr(cfg.immich, "bogus_field")


def test_album_mode_default(config_file: Path) -> None:
    cfg = load_config(config_file)
    assert cfg.sync.album_mode == "managed"
    assert cfg.sync.album_filter == "all"
    assert cfg.sync.album_min_rating == 0


def test_album_mode_hybrid(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]

[sync]
album_mode = "hybrid"
""")
    cfg = load_config(p)
    assert cfg.sync.album_mode == "hybrid"


def test_album_mode_invalid(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]

[sync]
album_mode = "bogus"
""")
    with pytest.raises(ValidationError):
        load_config(p)


@pytest.mark.parametrize("album_filter", ["all", "flagged", "unflagged", "rejected"])
def test_album_filter_valid(tmp_path: Path, album_filter: str) -> None:
    p = tmp_path / "config.toml"
    p.write_text(f"""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]

[sync]
album_filter = "{album_filter}"
""")
    cfg = load_config(p)
    assert cfg.sync.album_filter == album_filter


def test_album_filter_invalid(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]

[sync]
album_filter = "bogus"
""")
    with pytest.raises(ValidationError):
        load_config(p)


@pytest.mark.parametrize("rating", [-1, 6])
def test_album_min_rating_invalid(tmp_path: Path, rating: int) -> None:
    p = tmp_path / "config.toml"
    p.write_text(f"""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]

[sync]
album_min_rating = {rating}
""")
    with pytest.raises(ValidationError):
        load_config(p)


def test_album_rules(tmp_path: Path) -> None:
    p = tmp_path / "config.toml"
    p.write_text("""\
[[catalogs]]
catalog = "/tmp/test.lrcat"

[immich]
url = "http://localhost:2283"
api_key = "testkey123456"
library_paths = ["/immich/"]

[[album_rules]]
match = "Reise/*"
filter = "flagged"

[[album_rules]]
id = 123
min_rating = 3
""")
    cfg = load_config(p)
    assert len(cfg.album_rules) == 2
    assert cfg.album_rules[0].match == "Reise/*"
    assert cfg.album_rules[0].filter == "flagged"
    assert cfg.album_rules[1].id == 123
    assert cfg.album_rules[1].min_rating == 3
