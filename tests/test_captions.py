import json

import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.captions import (
    CaptionsResult,
    apply_captions_sync,
    plan_captions_sync,
)

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


def test_plan_new_captions(state: StateDB) -> None:
    captions = {"a.jpg": "Sunset photo", "b.jpg": "Mountain view"}
    resolved = {"a.jpg": "a1", "b.jpg": "a2"}
    to_set, to_clear = plan_captions_sync(captions, resolved, state)
    assert len(to_set) == 2
    assert to_set["a1"] == "Sunset photo"
    assert len(to_clear) == 0


def test_plan_idempotent(state: StateDB) -> None:
    state.set_meta("captions_snapshot", json.dumps({"a1": "Sunset photo"}))
    captions = {"a.jpg": "Sunset photo"}
    resolved = {"a.jpg": "a1"}
    to_set, to_clear = plan_captions_sync(captions, resolved, state)
    assert len(to_set) == 0
    assert len(to_clear) == 0


def test_plan_caption_changed(state: StateDB) -> None:
    state.set_meta("captions_snapshot", json.dumps({"a1": "Old caption"}))
    captions = {"a.jpg": "New caption"}
    resolved = {"a.jpg": "a1"}
    to_set, to_clear = plan_captions_sync(captions, resolved, state)
    assert to_set == {"a1": "New caption"}
    assert len(to_clear) == 0


def test_plan_caption_removed(state: StateDB) -> None:
    state.set_meta("captions_snapshot", json.dumps({"a1": "Sunset photo"}))
    to_set, to_clear = plan_captions_sync({}, {}, state)
    assert len(to_set) == 0
    assert to_clear == ["a1"]


def test_plan_unresolved_skipped(state: StateDB) -> None:
    captions = {"a.jpg": "Sunset photo"}
    resolved: dict[str, str] = {}
    to_set, to_clear = plan_captions_sync(captions, resolved, state)
    assert len(to_set) == 0
    assert len(to_clear) == 0


@respx.mock
@pytest.mark.anyio
async def test_apply_sets_descriptions(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets/a1").respond(json={"id": "a1"})
    respx.put(f"{API}/assets/a2").respond(json={"id": "a2"})
    result = await apply_captions_sync({"a1": "Sunset"}, ["a2"], client, state)
    assert result == CaptionsResult(set=1, cleared=1)
    snapshot = json.loads(state.get_meta("captions_snapshot") or "{}")
    assert snapshot == {"a1": "Sunset"}


@respx.mock
@pytest.mark.anyio
async def test_apply_audit_log(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/assets/a1").respond(json={"id": "a1"})
    await apply_captions_sync({"a1": "Hello"}, [], client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_captions"
