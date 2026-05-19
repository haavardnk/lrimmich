import httpx
import pytest
import respx

from lrimmich.clients.catalog import LrStack
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.stacks import StackAction, apply_stack_sync, plan_stack_sync

API = "http://immich.test/api"


@respx.mock
@pytest.mark.anyio
async def test_plan_create_stack(state: StateDB, client: ImmichClient) -> None:
    respx.get(f"{API}/stacks").mock(return_value=httpx.Response(200, json=[]))

    lr_stacks = [LrStack(stack_id=1, paths=["a.jpg", "b.jpg"])]
    resolved = {"a.jpg": "asset-a", "b.jpg": "asset-b"}

    actions = await plan_stack_sync(lr_stacks, resolved, state, client)

    assert len(actions) == 1
    assert actions[0].kind == "create"
    assert actions[0].asset_ids == ["asset-a", "asset-b"]


@respx.mock
@pytest.mark.anyio
async def test_plan_skip_single_resolved(state: StateDB, client: ImmichClient) -> None:
    respx.get(f"{API}/stacks").mock(return_value=httpx.Response(200, json=[]))

    lr_stacks = [LrStack(stack_id=1, paths=["a.jpg", "b.jpg"])]
    resolved = {"a.jpg": "asset-a"}

    actions = await plan_stack_sync(lr_stacks, resolved, state, client)

    assert actions == []


@respx.mock
@pytest.mark.anyio
async def test_plan_no_change(state: StateDB, client: ImmichClient) -> None:
    state.set_meta("stack:1", "immich-stack-1")
    respx.get(f"{API}/stacks").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "immich-stack-1",
                    "primaryAssetId": "asset-a",
                    "assets": [{"id": "asset-a"}, {"id": "asset-b"}],
                }
            ],
        )
    )

    lr_stacks = [LrStack(stack_id=1, paths=["a.jpg", "b.jpg"])]
    resolved = {"a.jpg": "asset-a", "b.jpg": "asset-b"}

    actions = await plan_stack_sync(lr_stacks, resolved, state, client)

    assert actions == []


@respx.mock
@pytest.mark.anyio
async def test_plan_update_stack(state: StateDB, client: ImmichClient) -> None:
    state.set_meta("stack:1", "immich-stack-1")
    respx.get(f"{API}/stacks").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": "immich-stack-1",
                    "primaryAssetId": "asset-a",
                    "assets": [{"id": "asset-a"}, {"id": "asset-b"}],
                }
            ],
        )
    )

    lr_stacks = [LrStack(stack_id=1, paths=["a.jpg", "b.jpg", "c.jpg"])]
    resolved = {"a.jpg": "asset-a", "b.jpg": "asset-b", "c.jpg": "asset-c"}

    actions = await plan_stack_sync(lr_stacks, resolved, state, client)

    assert len(actions) == 1
    assert actions[0].kind == "update"


@respx.mock
@pytest.mark.anyio
async def test_plan_delete_orphan(state: StateDB, client: ImmichClient) -> None:
    state.set_meta("stack:99", "immich-stack-99")
    respx.get(f"{API}/stacks").mock(return_value=httpx.Response(200, json=[]))

    actions = await plan_stack_sync([], {}, state, client)

    assert len(actions) == 1
    assert actions[0].kind == "delete"
    assert actions[0].immich_stack_id == "immich-stack-99"


@respx.mock
@pytest.mark.anyio
async def test_apply_create(state: StateDB, client: ImmichClient) -> None:
    respx.post(f"{API}/stacks").mock(
        return_value=httpx.Response(
            200, json={"id": "new-stack", "primaryAssetId": "a1"}
        )
    )

    actions = [
        StackAction(
            kind="create",
            lr_stack_id=1,
            asset_ids=["a1", "a2"],
            primary_asset_id="a1",
        )
    ]
    result = await apply_stack_sync(actions, client, state)

    assert result.created == 1
    assert state.get_meta("stack:1") == "new-stack"


@respx.mock
@pytest.mark.anyio
async def test_apply_delete(state: StateDB, client: ImmichClient) -> None:
    state.set_meta("stack:1", "old-stack")
    respx.delete(f"{API}/stacks/old-stack").mock(
        return_value=httpx.Response(200, json={})
    )

    actions = [
        StackAction(
            kind="delete",
            lr_stack_id=1,
            asset_ids=[],
            immich_stack_id="old-stack",
        )
    ]
    result = await apply_stack_sync(actions, client, state)

    assert result.deleted == 1
    assert state.get_meta("stack:1") == ""


@respx.mock
@pytest.mark.anyio
async def test_apply_update(state: StateDB, client: ImmichClient) -> None:
    state.set_meta("stack:1", "old-stack")
    respx.delete(f"{API}/stacks/old-stack").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.post(f"{API}/stacks").mock(
        return_value=httpx.Response(
            200, json={"id": "new-stack", "primaryAssetId": "a1"}
        )
    )

    actions = [
        StackAction(
            kind="update",
            lr_stack_id=1,
            asset_ids=["a1", "a2", "a3"],
            immich_stack_id="old-stack",
            primary_asset_id="a1",
        )
    ]
    result = await apply_stack_sync(actions, client, state)

    assert result.updated == 1
    assert state.get_meta("stack:1") == "new-stack"
