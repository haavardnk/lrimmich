import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.ratings import RatingsResult, apply_ratings_sync, plan_ratings_sync

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


def test_plan_new_ratings(state: StateDB) -> None:
    rated = {"photos/a.jpg": 3, "photos/b.jpg": 5}
    resolved = {"photos/a.jpg": "a1", "photos/b.jpg": "a2"}
    to_set, to_clear = plan_ratings_sync(rated, resolved, state)
    assert to_set == {"a1": 3, "a2": 5}
    assert to_clear == []


def test_plan_skips_unchanged(state: StateDB) -> None:
    state.replace_synced_ratings({"a1": 3})
    rated = {"photos/a.jpg": 3}
    resolved = {"photos/a.jpg": "a1"}
    to_set, to_clear = plan_ratings_sync(rated, resolved, state)
    assert to_set == {}
    assert to_clear == []


def test_plan_detects_changed(state: StateDB) -> None:
    state.replace_synced_ratings({"a1": 3})
    rated = {"photos/a.jpg": 5}
    resolved = {"photos/a.jpg": "a1"}
    to_set, to_clear = plan_ratings_sync(rated, resolved, state)
    assert to_set == {"a1": 5}
    assert to_clear == []


def test_plan_detects_removed(state: StateDB) -> None:
    state.replace_synced_ratings({"a1": 3, "a2": 5})
    rated = {"photos/a.jpg": 3}
    resolved = {"photos/a.jpg": "a1"}
    to_set, to_clear = plan_ratings_sync(rated, resolved, state)
    assert to_set == {}
    assert to_clear == ["a2"]


def test_plan_unresolved_skipped(state: StateDB) -> None:
    rated = {"photos/a.jpg": 3}
    resolved: dict[str, str] = {}
    to_set, to_clear = plan_ratings_sync(rated, resolved, state)
    assert to_set == {}
    assert to_clear == []


@respx.mock
def test_apply_batches_by_rating(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    result = apply_ratings_sync({"a1": 3, "a2": 3, "a3": 5}, [], client, state)
    assert result == RatingsResult(set=3, cleared=0)
    calls = [c for c in respx.calls if c.request.url.path == "/api/assets"]
    assert len(calls) == 2


@respx.mock
def test_apply_clears_removed(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    state.replace_synced_ratings({"a1": 3})
    result = apply_ratings_sync({}, ["a1"], client, state)
    assert result == RatingsResult(set=0, cleared=1)
    assert state.get_synced_ratings() == {}


def test_apply_empty_noop(client: ImmichClient, state: StateDB) -> None:
    result = apply_ratings_sync({}, [], client, state)
    assert result == RatingsResult(set=0, cleared=0)


@respx.mock
def test_apply_updates_state(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    apply_ratings_sync({"a1": 4}, [], client, state)
    assert state.get_synced_ratings() == {"a1": 4}


@respx.mock
def test_apply_logs_audit(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    apply_ratings_sync({"a1": 4}, [], client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_ratings"
