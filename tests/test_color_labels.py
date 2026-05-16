import json
from pathlib import Path

import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.color_labels import (
    ColorLabelsResult,
    apply_color_labels_sync,
    plan_color_labels_sync,
)
from lrimmich.sync.tags import TagAction

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


TAG_MAP = {"red": "t-red", "blue": "t-blue", "green": "t-green"}


def test_plan_tags_new_labels(state: StateDB) -> None:
    labels = {"a.jpg": "Red", "b.jpg": "Blue"}
    resolved = {"a.jpg": "a1", "b.jpg": "a2"}
    actions = plan_color_labels_sync(labels, resolved, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    assert len(tag_actions) == 2
    assert sum(len(a.asset_ids) for a in tag_actions) == 2


def test_plan_no_change_idempotent(state: StateDB) -> None:
    state.set_meta("color_labels_snapshot", json.dumps({"a1": "red"}))
    labels = {"a.jpg": "Red"}
    resolved = {"a.jpg": "a1"}
    actions = plan_color_labels_sync(labels, resolved, TAG_MAP, state)
    assert len(actions) == 0


def test_plan_label_changed(state: StateDB) -> None:
    state.set_meta("color_labels_snapshot", json.dumps({"a1": "red"}))
    labels = {"a.jpg": "Blue"}
    resolved = {"a.jpg": "a1"}
    actions = plan_color_labels_sync(labels, resolved, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    untag_actions = [a for a in actions if a.kind == "untag"]
    assert len(tag_actions) == 1
    assert tag_actions[0].tag_id == "t-blue"
    assert len(untag_actions) == 1
    assert untag_actions[0].tag_id == "t-red"


def test_plan_label_removed(state: StateDB) -> None:
    state.set_meta("color_labels_snapshot", json.dumps({"a1": "red"}))
    actions = plan_color_labels_sync({}, {}, TAG_MAP, state)
    untag_actions = [a for a in actions if a.kind == "untag"]
    assert len(untag_actions) == 1
    assert untag_actions[0].asset_ids == ["a1"]


def test_plan_unresolved_skipped(state: StateDB) -> None:
    labels = {"a.jpg": "Red"}
    resolved: dict[str, str] = {}
    actions = plan_color_labels_sync(labels, resolved, TAG_MAP, state)
    assert len(actions) == 0


@respx.mock
def test_apply_tags_and_untags(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/tags/t-red/assets").respond(json=None)
    respx.delete(f"{API}/tags/t-blue/assets").respond(json=None)

    actions = [
        TagAction(
            kind="tag", tag_id="t-red", tag_name="lr:color:red", asset_ids=["a1"]
        ),
        TagAction(
            kind="untag", tag_id="t-blue", tag_name="lr:color:blue", asset_ids=["a2"]
        ),
    ]
    result = apply_color_labels_sync(actions, {"a1": "red"}, client, state)
    assert result == ColorLabelsResult(tagged=1, untagged=1)
    snapshot = json.loads(state.get_meta("color_labels_snapshot") or "{}")
    assert snapshot == {"a1": "red"}


@respx.mock
def test_apply_logs_audit(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/tags/t-red/assets").respond(json=None)

    actions = [
        TagAction(kind="tag", tag_id="t-red", tag_name="lr:color:red", asset_ids=["a1"])
    ]
    apply_color_labels_sync(actions, {"a1": "red"}, client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_color_labels"
