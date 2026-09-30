import json

import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.color_labels import (
    ColorLabelsResult,
    apply_color_labels_sync,
    desired_color_tags,
    plan_color_labels_sync,
)
from lrimmich.sync.tags import TagAction

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


TAG_MAP = {"red": "t-red", "blue": "t-blue", "green": "t-green"}


@pytest.mark.parametrize(
    ("label", "overrides", "expected"),
    [
        ("Red", {}, {"a1": "red"}),
        ("Red", {"red": "Portfolio"}, {"a1": "Portfolio"}),
        ("Red", {"RED": "Portfolio"}, {"a1": "Portfolio"}),
        ("Blue", {"red": "Portfolio"}, {"a1": "blue"}),
        ("To Print", {}, {}),
        ("To Print", {"to print": "print"}, {"a1": "print"}),
    ],
)
def test_desired_color_tags(
    label: str, overrides: dict[str, str], expected: dict[str, str]
) -> None:
    resolved = {"a.jpg": "a1", "b.jpg": "a2"}
    assert desired_color_tags({"a.jpg": label}, resolved, overrides) == expected


def test_desired_color_tags_skips_unresolved() -> None:
    assert desired_color_tags({"a.jpg": "Red"}, {}, {}) == {}


def test_plan_tags_new_labels(state: StateDB) -> None:
    actions = plan_color_labels_sync({"a1": "red", "a2": "blue"}, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    assert len(tag_actions) == 2
    assert sum(len(a.asset_ids) for a in tag_actions) == 2


def test_plan_no_change_idempotent(state: StateDB) -> None:
    state.set_meta("color_labels_snapshot", json.dumps({"a1": "red"}))
    actions = plan_color_labels_sync({"a1": "red"}, TAG_MAP, state)
    assert len(actions) == 0


def test_plan_label_changed(state: StateDB) -> None:
    state.set_meta("color_labels_snapshot", json.dumps({"a1": "red"}))
    actions = plan_color_labels_sync({"a1": "blue"}, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    untag_actions = [a for a in actions if a.kind == "untag"]
    assert len(tag_actions) == 1
    assert tag_actions[0].tag_id == "t-blue"
    assert len(untag_actions) == 1
    assert untag_actions[0].tag_id == "t-red"


def test_plan_override_moves_tag(state: StateDB) -> None:
    state.set_meta("color_labels_snapshot", json.dumps({"a1": "red"}))
    tag_map = {**TAG_MAP, "Portfolio": "t-portfolio"}
    actions = plan_color_labels_sync({"a1": "Portfolio"}, tag_map, state)
    assert [(a.kind, a.tag_name, a.asset_ids) for a in actions] == [
        ("tag", "lr:color:Portfolio", ["a1"]),
        ("untag", "lr:color:red", ["a1"]),
    ]


def test_plan_label_removed(state: StateDB) -> None:
    state.set_meta("color_labels_snapshot", json.dumps({"a1": "red"}))
    actions = plan_color_labels_sync({}, TAG_MAP, state)
    untag_actions = [a for a in actions if a.kind == "untag"]
    assert len(untag_actions) == 1
    assert untag_actions[0].asset_ids == ["a1"]


@respx.mock
@pytest.mark.anyio
async def test_apply_tags_and_untags(client: ImmichClient, state: StateDB) -> None:
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
    result = await apply_color_labels_sync(actions, {"a1": "red"}, client, state)
    assert result == ColorLabelsResult(tagged=1, untagged=1)
    snapshot = json.loads(state.get_meta("color_labels_snapshot") or "{}")
    assert snapshot == {"a1": "red"}


@respx.mock
@pytest.mark.anyio
async def test_apply_logs_audit(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/tags/t-red/assets").respond(json=None)

    actions = [
        TagAction(kind="tag", tag_id="t-red", tag_name="lr:color:red", asset_ids=["a1"])
    ]
    await apply_color_labels_sync(actions, {"a1": "red"}, client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_color_labels"
