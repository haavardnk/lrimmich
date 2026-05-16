from pathlib import Path

import pytest
import respx

from lrimmich.catalog import LrCollection
from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB
from lrimmich.sync.favorites import (
    FavoritesResult,
    apply_favorites_sync,
    plan_favorites_sync,
)

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    db = StateDB(tmp_path / "state.db")
    db.upsert_path_cache("a.jpg", "asset-a", "/img/a.jpg")
    db.upsert_path_cache("b.jpg", "asset-b", "/img/b.jpg")
    db.upsert_path_cache("c.jpg", "asset-c", "/img/c.jpg")
    return db


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


def _col(
    id: int = 1,
    relative_paths: list[str] | None = None,
) -> LrCollection:
    return LrCollection(
        id=id,
        name="Album",
        full_name="Album",
        relative_paths=relative_paths or [],
    )


@pytest.mark.parametrize("scope", ["collections", "all"])
def test_scope_filtering_first_sync(scope: str, state: StateDB) -> None:
    col = _col(relative_paths=["a.jpg", "b.jpg"])
    flagged = {"a.jpg"}

    to_fav, to_unfav = plan_favorites_sync(flagged, scope, [col], state)

    assert to_fav == ["asset-a"]
    assert to_unfav == []


def test_favorite_added(state: StateDB) -> None:
    col = _col(relative_paths=["a.jpg"])
    flagged = {"a.jpg"}

    to_fav, _ = plan_favorites_sync(flagged, "collections", [col], state)

    assert to_fav == ["asset-a"]


def test_unfavorite_previously_synced(state: StateDB) -> None:
    col = _col(relative_paths=["a.jpg", "b.jpg"])
    state.replace_synced_favorites({"asset-a", "asset-b"})
    flagged: set[str] = set()

    _, to_unfav = plan_favorites_sync(flagged, "collections", [col], state)

    assert sorted(to_unfav) == ["asset-a", "asset-b"]


def test_unfavorite_skips_never_synced(state: StateDB) -> None:
    col = _col(relative_paths=["a.jpg", "b.jpg"])
    flagged: set[str] = set()

    _, to_unfav = plan_favorites_sync(flagged, "collections", [col], state)

    assert to_unfav == []


def test_no_drift_when_already_synced(state: StateDB) -> None:
    col = _col(relative_paths=["a.jpg", "b.jpg"])
    state.replace_synced_favorites({"asset-a"})
    flagged = {"a.jpg"}

    to_fav, to_unfav = plan_favorites_sync(flagged, "collections", [col], state)

    assert to_fav == []
    assert to_unfav == []


def test_unfavorite_does_not_touch_out_of_scope(
    state: StateDB,
) -> None:
    col = _col(relative_paths=["a.jpg"])
    state.replace_synced_favorites({"asset-a", "asset-c"})
    flagged: set[str] = set()

    _, to_unfav = plan_favorites_sync(flagged, "collections", [col], state)

    assert to_unfav == ["asset-a"]
    assert "asset-c" not in to_unfav


@respx.mock
def test_dry_run_no_mutations(state: StateDB) -> None:
    col = _col(relative_paths=["a.jpg"])
    flagged = {"a.jpg"}

    to_fav, _to_unfav = plan_favorites_sync(flagged, "collections", [col], state)

    assert to_fav == ["asset-a"]
    assert respx.calls.call_count == 0


@respx.mock
def test_apply(state: StateDB, client: ImmichClient) -> None:
    respx.put(f"{API}/assets").mock(
        return_value=__import__("httpx").Response(200, json=None)
    )

    result = apply_favorites_sync(["asset-a"], ["asset-b"], client, state)

    assert result == FavoritesResult(favorited=1, unfavorited=1)
    assert respx.calls.call_count == 2
    assert state.get_synced_favorites() == {"asset-a"}
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_favorites"


@respx.mock
def test_apply_updates_state(state: StateDB, client: ImmichClient) -> None:
    state.replace_synced_favorites({"asset-b"})
    respx.put(f"{API}/assets").mock(
        return_value=__import__("httpx").Response(200, json=None)
    )

    apply_favorites_sync(["asset-a"], ["asset-b"], client, state)

    assert state.get_synced_favorites() == {"asset-a"}


@respx.mock
def test_idempotency_no_changes(state: StateDB, client: ImmichClient) -> None:
    result = apply_favorites_sync([], [], client, state)

    assert result == FavoritesResult(favorited=0, unfavorited=0)
    assert respx.calls.call_count == 0
    assert len(state.get_audit_log()) == 0
