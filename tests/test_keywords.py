import json
from pathlib import Path

import pytest
import respx

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB
from lrimmich.sync.keywords import (
    KEYWORD_TAG_PREFIX,
    KeywordsResult,
    TagAction,
    _ensure_keyword_tags,
    apply_keywords_sync,
    plan_keywords_sync,
)

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


TAG_MAP = {"Nature": "t-nature", "Travel": "t-travel", "Nature/Trees": "t-trees"}


def test_plan_new_keywords(state: StateDB) -> None:
    keywords = {"a.jpg": ["Nature", "Travel"], "b.jpg": ["Nature/Trees"]}
    resolved = {"a.jpg": "a1", "b.jpg": "a2"}
    actions = plan_keywords_sync(keywords, resolved, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    total = sum(len(a.asset_ids) for a in tag_actions)
    assert total == 3


def test_plan_idempotent(state: StateDB) -> None:
    state.set_meta("keywords_snapshot", json.dumps({"a1": ["Nature"]}))
    keywords = {"a.jpg": ["Nature"]}
    resolved = {"a.jpg": "a1"}
    actions = plan_keywords_sync(keywords, resolved, TAG_MAP, state)
    assert len(actions) == 0


def test_plan_keyword_added(state: StateDB) -> None:
    state.set_meta("keywords_snapshot", json.dumps({"a1": ["Nature"]}))
    keywords = {"a.jpg": ["Nature", "Travel"]}
    resolved = {"a.jpg": "a1"}
    actions = plan_keywords_sync(keywords, resolved, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    assert len(tag_actions) == 1
    assert tag_actions[0].tag_id == "t-travel"


def test_plan_keyword_removed(state: StateDB) -> None:
    state.set_meta("keywords_snapshot", json.dumps({"a1": ["Nature", "Travel"]}))
    keywords = {"a.jpg": ["Nature"]}
    resolved = {"a.jpg": "a1"}
    actions = plan_keywords_sync(keywords, resolved, TAG_MAP, state)
    untag_actions = [a for a in actions if a.kind == "untag"]
    assert len(untag_actions) == 1
    assert untag_actions[0].tag_id == "t-travel"


def test_plan_asset_removed(state: StateDB) -> None:
    state.set_meta("keywords_snapshot", json.dumps({"a1": ["Nature"]}))
    actions = plan_keywords_sync({}, {}, TAG_MAP, state)
    untag_actions = [a for a in actions if a.kind == "untag"]
    assert len(untag_actions) == 1
    assert untag_actions[0].asset_ids == ["a1"]


def test_plan_unresolved_skipped(state: StateDB) -> None:
    keywords = {"a.jpg": ["Nature"]}
    resolved: dict[str, str] = {}
    actions = plan_keywords_sync(keywords, resolved, TAG_MAP, state)
    assert len(actions) == 0


@respx.mock
def test_ensure_keyword_tags_creates_missing(client: ImmichClient) -> None:
    respx.post(f"{API}/tags").respond(json={"id": "new-id", "value": "created"})
    result = _ensure_keyword_tags(client, [], {"Nature", "Travel"})
    assert len(result) == 2
    assert "Nature" in result
    assert "Travel" in result


@respx.mock
def test_ensure_keyword_tags_reuses_existing(client: ImmichClient) -> None:
    existing = [{"id": "e1", "value": f"{KEYWORD_TAG_PREFIX}Nature"}]
    respx.post(f"{API}/tags").respond(json={"id": "new-id", "value": "created"})
    result = _ensure_keyword_tags(client, existing, {"Nature", "Travel"})
    assert result["Nature"] == "e1"
    assert result["Travel"] == "new-id"


def test_plan_hierarchy_preserved(state: StateDB) -> None:
    keywords = {"a.jpg": ["Nature/Trees"]}
    resolved = {"a.jpg": "a1"}
    actions = plan_keywords_sync(keywords, resolved, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    assert len(tag_actions) == 1
    assert tag_actions[0].tag_name == f"{KEYWORD_TAG_PREFIX}Nature/Trees"


@respx.mock
def test_apply_tags_and_untags(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/tags/t-nature/assets").respond(json=None)
    respx.delete(f"{API}/tags/t-travel/assets").respond(json=None)
    actions = [
        TagAction(
            kind="tag",
            tag_id="t-nature",
            tag_name=f"{KEYWORD_TAG_PREFIX}Nature",
            asset_ids=["a1"],
        ),
        TagAction(
            kind="untag",
            tag_id="t-travel",
            tag_name=f"{KEYWORD_TAG_PREFIX}Travel",
            asset_ids=["a2"],
        ),
    ]
    result = apply_keywords_sync(actions, {"a1": ["Nature"]}, client, state)
    assert result == KeywordsResult(tagged=1, untagged=1)
    snapshot = json.loads(state.get_meta("keywords_snapshot") or "{}")
    assert snapshot == {"a1": ["Nature"]}


@respx.mock
def test_apply_logs_audit(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/tags/t-nature/assets").respond(json=None)
    actions = [
        TagAction(
            kind="tag",
            tag_id="t-nature",
            tag_name=f"{KEYWORD_TAG_PREFIX}Nature",
            asset_ids=["a1"],
        ),
    ]
    apply_keywords_sync(actions, {"a1": ["Nature"]}, client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_keywords"


def test_ensure_keyword_tags_no_create(client: ImmichClient) -> None:
    existing = [{"id": "e1", "value": f"{KEYWORD_TAG_PREFIX}Nature"}]
    result = _ensure_keyword_tags(client, existing, {"Nature", "Travel"}, create=False)
    assert result["Nature"] == "e1"
    assert result["Travel"].startswith("pending:")
