import json

import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.keywords import (
    KeywordsResult,
    apply_keywords_sync,
    plan_keywords_sync,
)
from lrimmich.sync.tags import TagAction

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


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


def test_plan_hierarchy_preserved(state: StateDB) -> None:
    keywords = {"a.jpg": ["Nature/Trees"]}
    resolved = {"a.jpg": "a1"}
    actions = plan_keywords_sync(keywords, resolved, TAG_MAP, state)
    tag_actions = [a for a in actions if a.kind == "tag"]
    assert len(tag_actions) == 1
    assert tag_actions[0].tag_name == "lr:keyword:Nature/Trees"


@respx.mock
@pytest.mark.anyio
async def test_apply_tags_and_untags(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/tags/t-nature/assets").respond(json=None)
    respx.delete(f"{API}/tags/t-travel/assets").respond(json=None)
    actions = [
        TagAction(
            kind="tag",
            tag_id="t-nature",
            tag_name="lr:keyword:Nature",
            asset_ids=["a1"],
        ),
        TagAction(
            kind="untag",
            tag_id="t-travel",
            tag_name="lr:keyword:Travel",
            asset_ids=["a2"],
        ),
    ]
    result = await apply_keywords_sync(actions, {"a1": ["Nature"]}, client, state)
    assert result == KeywordsResult(tagged=1, untagged=1)
    snapshot = json.loads(state.get_meta("keywords_snapshot") or "{}")
    assert snapshot == {"a1": ["Nature"]}


@respx.mock
@pytest.mark.anyio
async def test_apply_logs_audit(client: ImmichClient, state: StateDB) -> None:
    respx.put(f"{API}/tags/t-nature/assets").respond(json=None)
    actions = [
        TagAction(
            kind="tag",
            tag_id="t-nature",
            tag_name="lr:keyword:Nature",
            asset_ids=["a1"],
        ),
    ]
    await apply_keywords_sync(actions, {"a1": ["Nature"]}, client, state)
    logs = state.get_audit_log()
    assert len(logs) == 1
    assert logs[0]["action"] == "sync_keywords"
