from pathlib import Path

import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.covers import CoversResult, apply_covers_sync, plan_covers_sync

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


def _client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


def _state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


def test_plan_new_cover(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.upsert_album_ownership(1, "imm-1", "Travel")
    to_set, to_clear = plan_covers_sync(
        {1: "photos/best.jpg"}, {"photos/best.jpg": "a1"}, state
    )
    assert to_set == {"imm-1": "a1"}
    assert to_clear == []


def test_plan_skips_unchanged(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.upsert_album_ownership(1, "imm-1", "Travel")
    state.replace_synced_covers({"imm-1": "a1"})
    to_set, to_clear = plan_covers_sync(
        {1: "photos/best.jpg"}, {"photos/best.jpg": "a1"}, state
    )
    assert to_set == {}
    assert to_clear == []


def test_plan_detects_changed(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.upsert_album_ownership(1, "imm-1", "Travel")
    state.replace_synced_covers({"imm-1": "a1"})
    to_set, to_clear = plan_covers_sync(
        {1: "photos/new.jpg"}, {"photos/new.jpg": "a2"}, state
    )
    assert to_set == {"imm-1": "a2"}
    assert to_clear == []


def test_plan_detects_removed(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.upsert_album_ownership(1, "imm-1", "Travel")
    state.replace_synced_covers({"imm-1": "a1"})
    to_set, to_clear = plan_covers_sync({}, {}, state)
    assert to_set == {}
    assert to_clear == ["imm-1"]


def test_plan_skips_unresolved(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.upsert_album_ownership(1, "imm-1", "Travel")
    to_set, to_clear = plan_covers_sync({1: "photos/missing.jpg"}, {}, state)
    assert to_set == {}
    assert to_clear == []


def test_plan_skips_unowned(tmp_path: Path) -> None:
    state = _state(tmp_path)
    to_set, to_clear = plan_covers_sync(
        {99: "photos/best.jpg"}, {"photos/best.jpg": "a1"}, state
    )
    assert to_set == {}
    assert to_clear == []


@respx.mock
def test_apply_sets_cover(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.patch(f"{API}/albums/imm-1").respond(json={"id": "imm-1"})
    result = apply_covers_sync({"imm-1": "a1"}, [], client, state)
    assert result == CoversResult(set=1, cleared=0)
    req = respx.calls[0].request
    assert b"albumThumbnailAssetId" in req.content
    assert b"a1" in req.content


@respx.mock
def test_apply_clears_cover(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    state.replace_synced_covers({"imm-1": "a1"})
    respx.patch(f"{API}/albums/imm-1").respond(json={"id": "imm-1"})
    result = apply_covers_sync({}, ["imm-1"], client, state)
    assert result == CoversResult(set=0, cleared=1)
    assert state.get_synced_covers() == {}


@respx.mock
def test_apply_updates_state(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.patch(f"{API}/albums/imm-1").respond(json={"id": "imm-1"})
    apply_covers_sync({"imm-1": "a1"}, [], client, state)
    assert state.get_synced_covers() == {"imm-1": "a1"}


@respx.mock
def test_apply_logs_audit(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.patch(f"{API}/albums/imm-1").respond(json={"id": "imm-1"})
    apply_covers_sync({"imm-1": "a1"}, [], client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_covers"


def test_apply_empty_noop(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    result = apply_covers_sync({}, [], client, state)
    assert result == CoversResult(set=0, cleared=0)
