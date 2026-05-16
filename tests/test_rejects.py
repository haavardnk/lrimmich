from pathlib import Path

import pytest
import respx

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB
from lrimmich.sync.rejects import RejectsResult, apply_rejects_sync, plan_rejects_sync

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


@pytest.mark.parametrize(
    ("rejected", "resolved", "exp_archive", "exp_unarchive"),
    [
        (
            {"a.jpg"},
            {"a.jpg": "a1", "b.jpg": "a2"},
            ["a1"],
            ["a2"],
        ),
        (
            set(),
            {"a.jpg": "a1"},
            [],
            ["a1"],
        ),
        (
            {"a.jpg"},
            {},
            [],
            [],
        ),
    ],
    ids=["one-rejected", "none-rejected", "unresolved"],
)
def test_plan_rejects_sync(
    rejected: set[str],
    resolved: dict[str, str],
    exp_archive: list[str],
    exp_unarchive: list[str],
) -> None:
    to_arch, to_unarch = plan_rejects_sync(rejected, resolved)
    assert to_arch == exp_archive
    assert to_unarch == exp_unarchive


@respx.mock
def test_apply_archives_and_unarchives(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    result = apply_rejects_sync(["a1"], ["a2"], client, state)
    assert result == RejectsResult(archived=1, unarchived=1)
    calls = [c for c in respx.calls if c.request.url.path == "/api/assets"]
    assert len(calls) == 2


def test_apply_empty_noop(client: ImmichClient, state: StateDB) -> None:
    result = apply_rejects_sync([], [], client, state)
    assert result == RejectsResult(archived=0, unarchived=0)


@respx.mock
def test_apply_logs_audit(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets").respond(json=None)
    apply_rejects_sync(["a1"], [], client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_rejects"
