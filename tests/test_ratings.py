from pathlib import Path

import pytest
import respx

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB
from lrimmich.sync.ratings import RatingsResult, apply_ratings_sync, plan_ratings_sync

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


@pytest.mark.parametrize(
    ("rated", "resolved", "expected"),
    [
        (
            {"photos/a.jpg": 3, "photos/b.jpg": 5},
            {"photos/a.jpg": "a1", "photos/b.jpg": "a2"},
            {"a1": 3, "a2": 5},
        ),
        (
            {"photos/a.jpg": 3},
            {"photos/b.jpg": "a2"},
            {},
        ),
        (
            {},
            {"photos/a.jpg": "a1"},
            {},
        ),
    ],
    ids=["all-resolved", "unresolved-skipped", "no-ratings"],
)
def test_plan_ratings_sync(
    rated: dict[str, int],
    resolved: dict[str, str],
    expected: dict[str, int],
) -> None:
    assert plan_ratings_sync(rated, resolved) == expected


@respx.mock
def test_apply_batches_by_rating(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    plan = {"a1": 3, "a2": 3, "a3": 5}
    result = apply_ratings_sync(plan, client, state)
    assert result == RatingsResult(updated=3)
    calls = [c for c in respx.calls if c.request.url.path == "/api/assets"]
    assert len(calls) == 2


def test_apply_empty_plan(client: ImmichClient, state: StateDB) -> None:
    result = apply_ratings_sync({}, client, state)
    assert result == RatingsResult(updated=0)


@respx.mock
def test_apply_logs_audit(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    apply_ratings_sync({"a1": 4}, client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_ratings"
