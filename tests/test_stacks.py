import json
from typing import Any

import httpx
import pytest
import respx

from lrimmich.clients.catalog import LrStack
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.stacks import SNAPSHOT_KEY, apply_stack_sync, plan_stack_sync

API = "http://immich.test/api"
RESOLVED = {"a.jpg": "a", "b.jpg": "b", "c.jpg": "c"}


def _stack(stack_id: str, *asset_ids: str) -> dict[str, Any]:
    return {
        "id": stack_id,
        "primaryAssetId": asset_ids[0],
        "assets": [{"id": a} for a in asset_ids],
    }


@respx.mock
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("paths", "owned", "existing", "expected"),
    [
        (["a.jpg", "b.jpg"], {}, [], [("create", ["a", "b"], None)]),
        (["a.jpg", "x.jpg"], {}, [], []),
        (["a.jpg", "a.jpg"], {}, [], []),
        (["a.jpg", "b.jpg"], {"1": "s1"}, [_stack("s1", "a", "b")], []),
        (
            ["a.jpg", "b.jpg", "c.jpg"],
            {"1": "s1"},
            [_stack("s1", "a", "b")],
            [("update", ["a", "b", "c"], "s1")],
        ),
        (
            ["b.jpg", "a.jpg"],
            {"1": "s1"},
            [_stack("s1", "a", "b")],
            [("update", ["b", "a"], "s1")],
        ),
        (["a.jpg", "b.jpg"], {"1": "gone"}, [], [("create", ["a", "b"], None)]),
        (
            ["a.jpg", "x.jpg"],
            {"1": "s1"},
            [_stack("s1", "a", "b")],
            [("delete", [], "s1")],
        ),
        ([], {"1": "gone"}, [], []),
    ],
)
async def test_plan(
    state: StateDB,
    client: ImmichClient,
    paths: list[str],
    owned: dict[str, str],
    existing: list[dict[str, Any]],
    expected: list[tuple[str, list[str], str | None]],
) -> None:
    state.set_meta(SNAPSHOT_KEY, json.dumps(owned))
    respx.get(f"{API}/stacks").respond(json=existing)
    lr_stacks = [LrStack(stack_id=1, paths=paths)] if paths else []

    plan = await plan_stack_sync(lr_stacks, RESOLVED, state, client)

    assert [(a.kind, a.asset_ids, a.immich_stack_id) for a in plan.actions] == expected


@respx.mock
@pytest.mark.anyio
async def test_apply_replaces_and_forgets(state: StateDB, client: ImmichClient) -> None:
    state.set_meta(SNAPSHOT_KEY, json.dumps({"1": "s1", "2": "s2", "3": "gone"}))
    respx.get(f"{API}/stacks").respond(
        json=[_stack("s1", "a", "b"), _stack("s2", "c", "d")]
    )
    deleted = respx.delete(url__regex=rf"{API}/stacks/.+").respond(status_code=204)
    respx.post(f"{API}/stacks").respond(json={"id": "new"})
    lr_stacks = [
        LrStack(stack_id=1, paths=["a.jpg", "b.jpg", "c.jpg"]),
        LrStack(stack_id=4, paths=["a.jpg", "b.jpg"]),
    ]
    plan = await plan_stack_sync(lr_stacks, RESOLVED, state, client)

    await apply_stack_sync(plan, client, state)

    assert sorted(c.request.url.path for c in deleted.calls) == [
        "/api/stacks/s1",
        "/api/stacks/s2",
    ]
    assert json.loads(state.get_meta(SNAPSHOT_KEY) or "") == {"1": "new", "4": "new"}
    assert [log["action"] for log in state.get_audit_log()] == [
        "delete_stack",
        "create_stack",
        "update_stack",
    ]


@respx.mock
@pytest.mark.anyio
async def test_apply_keeps_ownership_on_failure(
    state: StateDB, client: ImmichClient
) -> None:
    state.set_meta(SNAPSHOT_KEY, json.dumps({"1": "s1"}))
    respx.get(f"{API}/stacks").respond(json=[_stack("s1", "a", "b")])
    respx.delete(f"{API}/stacks/s1").respond(status_code=204)
    respx.post(f"{API}/stacks").mock(
        side_effect=[
            httpx.Response(200, json={"id": "new-2"}),
            httpx.Response(400),
        ]
    )
    lr_stacks = [
        LrStack(stack_id=2, paths=["b.jpg", "c.jpg"]),
        LrStack(stack_id=1, paths=["a.jpg", "b.jpg", "c.jpg"]),
    ]
    plan = await plan_stack_sync(lr_stacks, RESOLVED, state, client)

    with pytest.raises(httpx.HTTPStatusError):
        await apply_stack_sync(plan, client, state)

    assert json.loads(state.get_meta(SNAPSHOT_KEY) or "") == {"2": "new-2"}
