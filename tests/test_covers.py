from pathlib import Path

import pytest
import respx

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.covers import (
    SNAPSHOT_KEY,
    CoversResult,
    apply_covers_sync,
    pick_cover_candidates,
    plan_covers_sync,
)
from lrimmich.utils.config import AlbumFilter, Config

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


def _client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


def _state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


@pytest.mark.parametrize(
    "previous,candidates,expected",
    [
        (None, ["p/a.jpg"], {"imm-1": "a1"}),
        ("a1", ["p/a.jpg"], {}),
        ("a1", ["p/b.jpg"], {"imm-1": "a2"}),
        ("a2", ["p/a.jpg", "p/b.jpg"], {}),
    ],
)
def test_plan_sets_cover(
    tmp_path: Path,
    previous: str | None,
    candidates: list[str],
    expected: dict[str, str],
) -> None:
    state = _state(tmp_path)
    state.upsert_album_ownership(1, "imm-1", "Travel")
    if previous:
        state.set_snapshot(SNAPSHOT_KEY, {"imm-1": previous})
    to_set, stale = plan_covers_sync(
        {1: candidates}, {"p/a.jpg": "a1", "p/b.jpg": "a2"}, state
    )
    assert to_set == expected
    assert stale == []


@pytest.mark.parametrize("owned", [True, False])
def test_plan_forgets_cover_without_candidates(tmp_path: Path, owned: bool) -> None:
    state = _state(tmp_path)
    if owned:
        state.upsert_album_ownership(1, "imm-1", "Travel")
    state.set_snapshot(SNAPSHOT_KEY, {"imm-1": "a1"})
    to_set, stale = plan_covers_sync({}, {}, state)
    assert to_set == {}
    assert stale == ["imm-1"]


def test_plan_skips_unresolved(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.upsert_album_ownership(1, "imm-1", "Travel")
    to_set, stale = plan_covers_sync({1: ["photos/missing.jpg"]}, {}, state)
    assert to_set == {}
    assert stale == []


def test_plan_skips_unowned(tmp_path: Path) -> None:
    state = _state(tmp_path)
    to_set, stale = plan_covers_sync(
        {99: ["photos/best.jpg"]}, {"photos/best.jpg": "a1"}, state
    )
    assert to_set == {}
    assert stale == []


@pytest.mark.parametrize(
    "album_filter,unresolved,expected",
    [
        ("all", set(), ["r/rejected5.jpg"]),
        ("unflagged", set(), ["r/rated3.jpg", "r/also3.jpg"]),
        ("unflagged", {"r/rated3.jpg", "r/also3.jpg"}, ["r/flagged.jpg"]),
        ("unflagged", {"r/rated3.jpg", "r/also3.jpg", "r/flagged.jpg"}, None),
    ],
)
def test_pick_cover_from_album_paths(
    album_filter: AlbumFilter, unresolved: set[str], expected: list[str] | None
) -> None:
    paths = [
        "r/plain.jpg",
        "r/flagged.jpg",
        "r/rated3.jpg",
        "r/also3.jpg",
        "r/rejected5.jpg",
    ]
    collection = LrCollection(id=1, name="T", full_name="T", relative_paths=paths)
    cfg = Config(
        catalogs=[{"catalog": "x.lrcat"}],
        immich={"url": IMMICH_URL, "api_key": "k", "library_paths": [""]},
        sync={"album_filter": album_filter},
    )
    covers = pick_cover_candidates(
        [collection],
        cfg,
        {p: p for p in paths if p not in unresolved},
        {"r/flagged.jpg"},
        {"r/rejected5.jpg"},
        {"r/rated3.jpg": 3, "r/also3.jpg": 3, "r/rejected5.jpg": 5},
    )
    assert covers.get(1) == expected


@respx.mock
@pytest.mark.anyio
async def test_apply_sets_cover(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.patch(f"{API}/albums/imm-1").respond(json={"id": "imm-1"})
    result = await apply_covers_sync({"imm-1": "a1"}, [], client, state)
    assert result == CoversResult(set=1)
    req = respx.calls[0].request
    assert b"albumThumbnailAssetId" in req.content
    assert b"a1" in req.content


@respx.mock
@pytest.mark.anyio
async def test_apply_stale_only_forgets_cover(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    state.set_snapshot(SNAPSHOT_KEY, {"imm-1": "a1"})
    result = await apply_covers_sync({}, ["imm-1"], client, state)
    assert result == CoversResult(set=0)
    assert state.get_snapshot(SNAPSHOT_KEY) == {}
    assert not respx.calls


@respx.mock
@pytest.mark.anyio
async def test_apply_updates_state(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.patch(f"{API}/albums/imm-1").respond(json={"id": "imm-1"})
    await apply_covers_sync({"imm-1": "a1"}, [], client, state)
    assert state.get_snapshot(SNAPSHOT_KEY) == {"imm-1": "a1"}


@respx.mock
@pytest.mark.anyio
async def test_apply_logs_audit(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.patch(f"{API}/albums/imm-1").respond(json={"id": "imm-1"})
    await apply_covers_sync({"imm-1": "a1"}, [], client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_covers"


@pytest.mark.anyio
async def test_apply_empty_noop(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    result = await apply_covers_sync({}, [], client, state)
    assert result == CoversResult(set=0)
