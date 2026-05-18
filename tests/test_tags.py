import json
from pathlib import Path

import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.tags import TagAction, TagSyncResult, apply_tag_actions, ensure_tags

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@respx.mock
def test_ensure_tags_creates_missing(client: ImmichClient) -> None:
    respx.post(f"{API}/tags").respond(json={"id": "new-id", "value": "pre:red"})
    result = ensure_tags(client, [], {"red", "blue"}, "pre:")
    assert "red" in result
    assert "blue" in result


@respx.mock
def test_ensure_tags_reuses_existing(client: ImmichClient) -> None:
    existing = [{"id": "e1", "value": "pre:red"}]
    respx.post(f"{API}/tags").respond(json={"id": "new-id", "value": "pre:blue"})
    result = ensure_tags(client, existing, {"red", "blue"}, "pre:")
    assert result["red"] == "e1"
    assert result["blue"] == "new-id"


def test_ensure_tags_no_create(client: ImmichClient) -> None:
    existing = [{"id": "e1", "value": "pre:red"}]
    result = ensure_tags(client, existing, {"red", "blue"}, "pre:", create=False)
    assert result["red"] == "e1"
    assert result["blue"] is None


@respx.mock
def test_apply_tag_actions(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    respx.put(f"{API}/tags/t1/assets").respond(json=None)
    respx.delete(f"{API}/tags/t2/assets").respond(json=None)
    actions = [
        TagAction(kind="tag", tag_id="t1", tag_name="pre:a", asset_ids=["a1"]),
        TagAction(kind="untag", tag_id="t2", tag_name="pre:b", asset_ids=["a2"]),
    ]
    result = apply_tag_actions(
        actions, {"a1": "a"}, client, state, "test_snap", "test_action"
    )
    assert result == TagSyncResult(tagged=1, untagged=1)
    assert json.loads(state.get_meta("test_snap") or "{}") == {"a1": "a"}


@respx.mock
def test_apply_tag_actions_logs_audit(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    respx.put(f"{API}/tags/t1/assets").respond(json=None)
    actions = [
        TagAction(kind="tag", tag_id="t1", tag_name="pre:a", asset_ids=["a1"]),
    ]
    apply_tag_actions(actions, {"a1": "a"}, client, state, "snap", "my_action")
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "my_action"


def test_apply_empty_noop(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    result = apply_tag_actions([], {}, client, state, "snap", "noop")
    assert result == TagSyncResult(tagged=0, untagged=0)
