import json
from pathlib import Path

import pytest

from lrimmich.clients.state import StateDB


@pytest.fixture()
def db(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "test_state.db")


def test_schema_creation(db: StateDB) -> None:
    assert db.get_meta("schema_version") == "1"


def test_migration_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "test.db"
    db1 = StateDB(path)
    db1.set_meta("custom", "value")
    db1.close()
    db2 = StateDB(path)
    assert db2.get_meta("schema_version") == "1"
    assert db2.get_meta("custom") == "value"
    db2.close()


def test_meta_set_get(db: StateDB) -> None:
    db.set_meta("last_sync", "12345")
    assert db.get_meta("last_sync") == "12345"
    db.set_meta("last_sync", "99999")
    assert db.get_meta("last_sync") == "99999"


def test_meta_missing(db: StateDB) -> None:
    assert db.get_meta("nonexistent") is None


def test_path_cache_upsert_and_get(db: StateDB) -> None:
    db.upsert_path_cache("2024/a.jpg", "asset-1", "/ext/2024/a.jpg")
    assert db.get_cached_asset("2024/a.jpg") == "asset-1"


def test_path_cache_overwrite(db: StateDB) -> None:
    db.upsert_path_cache("a.jpg", "old", "/ext/a.jpg")
    db.upsert_path_cache("a.jpg", "new", "/ext/a.jpg")
    assert db.get_cached_asset("a.jpg") == "new"


def test_path_cache_miss(db: StateDB) -> None:
    assert db.get_cached_asset("missing.jpg") is None


def test_get_all_cached_paths(db: StateDB) -> None:
    db.upsert_path_cache("a.jpg", "x1", "/ext/a.jpg")
    db.upsert_path_cache("b.jpg", "x2", "/ext/b.jpg")
    result = db.get_all_cached_paths()
    assert result == {"a.jpg": "x1", "b.jpg": "x2"}


def test_upsert_path_cache_bulk(db: StateDB) -> None:
    db.upsert_path_cache_bulk(
        [
            ("a.jpg", "id-a", "/ext/a.jpg"),
            ("b.jpg", "id-b", "/ext/b.jpg"),
            ("c.jpg", "id-c", "/ext/c.jpg"),
        ]
    )
    assert db.get_all_cached_paths() == {
        "a.jpg": "id-a",
        "b.jpg": "id-b",
        "c.jpg": "id-c",
    }


def test_upsert_path_cache_bulk_overwrites(db: StateDB) -> None:
    db.upsert_path_cache("a.jpg", "old", "/ext/a.jpg")
    db.upsert_path_cache_bulk([("a.jpg", "new", "/ext/a.jpg")])
    assert db.get_cached_asset("a.jpg") == "new"


def test_upsert_path_cache_bulk_empty(db: StateDB) -> None:
    db.upsert_path_cache_bulk([])
    assert db.get_all_cached_paths() == {}


def test_album_ownership_upsert(db: StateDB) -> None:
    db.upsert_album_ownership(1, "immich-abc", "Vacation")
    row = db.get_album_ownership(1)
    assert row is not None
    assert row["immich_album_id"] == "immich-abc"
    assert row["last_name"] == "Vacation"


def test_album_ownership_update(db: StateDB) -> None:
    db.upsert_album_ownership(1, "immich-abc", "Old Name")
    db.upsert_album_ownership(1, "immich-abc", "New Name")
    row = db.get_album_ownership(1)
    assert row is not None
    assert row["last_name"] == "New Name"


def test_album_ownership_missing(db: StateDB) -> None:
    assert db.get_album_ownership(999) is None


def test_album_by_immich_id(db: StateDB) -> None:
    db.upsert_album_ownership(5, "album-xyz", "Trip")
    row = db.get_album_by_immich_id("album-xyz")
    assert row is not None
    assert row["lr_collection_id"] == 5


def test_get_all_owned_albums(db: StateDB) -> None:
    db.upsert_album_ownership(1, "a1", "Album 1")
    db.upsert_album_ownership(2, "a2", "Album 2")
    albums = db.get_all_owned_albums()
    assert len(albums) == 2


def test_remove_album_ownership(db: StateDB) -> None:
    db.upsert_album_ownership(1, "a1", "Test")
    db.remove_album_ownership(1)
    assert db.get_album_ownership(1) is None


def test_audit_log_append(db: StateDB) -> None:
    db.append_audit_log("create", "album", "a1", {"name": "Vacation"})
    logs = db.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "create"
    assert logs[0]["target_type"] == "album"
    assert logs[0]["target_id"] == "a1"
    assert json.loads(logs[0]["payload_json"]) == {"name": "Vacation"}


def test_audit_log_no_payload(db: StateDB) -> None:
    db.append_audit_log("delete", "album", "a1")
    logs = db.get_audit_log()
    assert logs[0]["payload_json"] is None


def test_audit_log_ordering(db: StateDB) -> None:
    db.append_audit_log("first", "album", "a1")
    db.append_audit_log("second", "album", "a2")
    logs = db.get_audit_log()
    assert logs[0]["action"] == "second"
    assert logs[1]["action"] == "first"


def test_creates_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "nested" / "state.db"
    db = StateDB(path)
    assert db.get_meta("schema_version") == "1"
    db.close()
