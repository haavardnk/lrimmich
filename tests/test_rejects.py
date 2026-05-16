from pathlib import Path

import respx

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB
from lrimmich.sync.rejects import RejectsResult, apply_rejects_sync, plan_rejects_sync

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


def _client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


def _state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


def test_plan_new_rejects(tmp_path: Path) -> None:
    state = _state(tmp_path)
    to_arch, to_unarch = plan_rejects_sync(
        {"a.jpg"}, {"a.jpg": "a1", "b.jpg": "a2"}, state
    )
    assert to_arch == ["a1"]
    assert to_unarch == []


def test_plan_skips_unchanged(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.replace_synced_rejects({"a1"})
    to_arch, to_unarch = plan_rejects_sync({"a.jpg"}, {"a.jpg": "a1"}, state)
    assert to_arch == []
    assert to_unarch == []


def test_plan_detects_unreject(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.replace_synced_rejects({"a1"})
    to_arch, to_unarch = plan_rejects_sync(set(), {"a.jpg": "a1"}, state)
    assert to_arch == []
    assert to_unarch == ["a1"]


def test_plan_unresolved_skipped(tmp_path: Path) -> None:
    state = _state(tmp_path)
    to_arch, to_unarch = plan_rejects_sync({"a.jpg"}, {}, state)
    assert to_arch == []
    assert to_unarch == []


def test_plan_no_false_unarchive(tmp_path: Path) -> None:
    state = _state(tmp_path)
    to_arch, to_unarch = plan_rejects_sync(set(), {"a.jpg": "a1"}, state)
    assert to_arch == []
    assert to_unarch == []


@respx.mock
def test_apply_archives_and_unarchives(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.put(f"{API}/assets").respond(json=None)
    result = apply_rejects_sync(["a1"], ["a2"], client, state)
    assert result == RejectsResult(archived=1, unarchived=1)
    assert state.get_synced_rejects() == {"a1"}


@respx.mock
def test_apply_updates_state(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    state.replace_synced_rejects({"a2"})
    respx.put(f"{API}/assets").respond(json=None)
    apply_rejects_sync(["a1"], ["a2"], client, state)
    assert state.get_synced_rejects() == {"a1"}


def test_apply_empty_noop(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    result = apply_rejects_sync([], [], client, state)
    assert result == RejectsResult(archived=0, unarchived=0)


@respx.mock
def test_apply_logs_audit(tmp_path: Path) -> None:
    client = _client()
    state = _state(tmp_path)
    respx.put(f"{API}/assets").respond(json=None)
    apply_rejects_sync(["a1"], [], client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_rejects"
