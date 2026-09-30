from pathlib import Path

import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.favorites import (
    SNAPSHOT_KEY,
    FavoritesResult,
    apply_favorites_sync,
    plan_favorites_sync,
)

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"
RESOLVED = {"a.jpg": "asset-a", "b.jpg": "asset-b"}


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


def test_favorite_added(state: StateDB) -> None:
    to_fav, to_unfav = plan_favorites_sync({"a.jpg"}, RESOLVED, state)

    assert to_fav == ["asset-a"]
    assert to_unfav == []


def test_unfavorite_previously_synced(state: StateDB) -> None:
    state.set_snapshot(SNAPSHOT_KEY, ["asset-a", "asset-b"])

    _, to_unfav = plan_favorites_sync(set(), RESOLVED, state)

    assert sorted(to_unfav) == ["asset-a", "asset-b"]


def test_unfavorite_skips_never_synced(state: StateDB) -> None:
    _, to_unfav = plan_favorites_sync(set(), RESOLVED, state)

    assert to_unfav == []


def test_no_drift_when_already_synced(state: StateDB) -> None:
    state.set_snapshot(SNAPSHOT_KEY, ["asset-a"])

    to_fav, to_unfav = plan_favorites_sync({"a.jpg"}, RESOLVED, state)

    assert to_fav == []
    assert to_unfav == []


def test_unfavorite_does_not_touch_out_of_scope(state: StateDB) -> None:
    state.set_snapshot(SNAPSHOT_KEY, ["asset-a", "asset-c"])

    _, to_unfav = plan_favorites_sync(set(), RESOLVED, state)

    assert to_unfav == ["asset-a"]


@respx.mock
def test_dry_run_no_mutations(state: StateDB) -> None:
    to_fav, _to_unfav = plan_favorites_sync({"a.jpg"}, RESOLVED, state)

    assert to_fav == ["asset-a"]
    assert respx.calls.call_count == 0


@respx.mock
@pytest.mark.anyio
async def test_apply(state: StateDB, client: ImmichClient) -> None:
    respx.patch(f"{API}/assets").mock(
        return_value=__import__("httpx").Response(200, json=None)
    )

    result = await apply_favorites_sync(["asset-a"], ["asset-b"], client, state)

    assert result == FavoritesResult(favorited=1, unfavorited=1)
    assert respx.calls.call_count == 2
    assert state.get_snapshot(SNAPSHOT_KEY) == ["asset-a"]
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_favorites"


@respx.mock
@pytest.mark.anyio
async def test_apply_updates_state(state: StateDB, client: ImmichClient) -> None:
    state.set_snapshot(SNAPSHOT_KEY, ["asset-b"])
    respx.patch(f"{API}/assets").mock(
        return_value=__import__("httpx").Response(200, json=None)
    )

    await apply_favorites_sync(["asset-a"], ["asset-b"], client, state)

    assert state.get_snapshot(SNAPSHOT_KEY) == ["asset-a"]


@respx.mock
@pytest.mark.anyio
async def test_idempotency_no_changes(state: StateDB, client: ImmichClient) -> None:
    result = await apply_favorites_sync([], [], client, state)

    assert result == FavoritesResult(favorited=0, unfavorited=0)
    assert respx.calls.call_count == 0
    assert len(state.get_audit_log()) == 0
