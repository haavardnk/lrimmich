from pathlib import Path

import httpx
import pytest
import respx

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.albums import (
    AlbumAction,
    DeleteThresholdExceeded,
    RemoveLimitExceeded,
    apply_album_sync,
    format_album_name,
    plan_album_sync,
)
from lrimmich.utils.config import SafetyConfig

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


def _col(
    id: int = 1,
    name: str = "Album",
    full_name: str = "Album",
    relative_paths: list[str] | None = None,
) -> LrCollection:
    return LrCollection(
        id=id,
        name=name,
        full_name=full_name,
        relative_paths=relative_paths or [],
    )


@pytest.mark.parametrize(
    "full_name,fmt,expected",
    [
        ("Travel/Europe/Italy", "{path}", "Travel/Europe/Italy"),
        ("Travel/Europe/Italy", "{name}", "Italy"),
        ("Travel/Europe/Italy", "{parent}/{name}", "Europe/Italy"),
        ("Travel/Europe/Italy", "Photos - {name}", "Photos - Italy"),
        ("TopLevel", "{name}", "TopLevel"),
        ("TopLevel", "{parent}/{name}", "/TopLevel"),
    ],
)
def test_format_album_name(full_name: str, fmt: str, expected: str) -> None:
    col = _col(full_name=full_name)
    assert format_album_name(col, fmt) == expected


@respx.mock
def test_create_new_album(state: StateDB, client: ImmichClient) -> None:
    col = _col(id=10, full_name="Travel/Japan", relative_paths=["a.jpg", "b.jpg"])
    resolved = {"a.jpg": "asset-1", "b.jpg": "asset-2"}

    actions = plan_album_sync([col], resolved, state, client)

    assert len(actions) == 1
    assert actions[0].kind == "create"
    assert actions[0].album_name == "Travel/Japan"
    assert sorted(actions[0].asset_ids) == ["asset-1", "asset-2"]


@respx.mock
def test_skip_empty_collection(state: StateDB, client: ImmichClient) -> None:
    col = _col(id=10, full_name="Empty")
    resolved: dict[str, str] = {}

    actions = plan_album_sync([col], resolved, state, client, skip_empty=True)
    assert len(actions) == 0

    actions = plan_album_sync([col], resolved, state, client, skip_empty=False)
    assert len(actions) == 1
    assert actions[0].kind == "create"


@respx.mock
def test_skip_empty_deletes_owned_album(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "album-1", "NowEmpty")
    col = _col(id=10, full_name="NowEmpty")
    resolved: dict[str, str] = {}

    actions = plan_album_sync([col], resolved, state, client, skip_empty=True)
    assert len(actions) == 1
    assert actions[0].kind == "delete"
    assert actions[0].immich_album_id == "album-1"


@respx.mock
def test_create_and_share(state: StateDB, client: ImmichClient) -> None:
    col = _col(id=10, full_name="Shared")
    resolved: dict[str, str] = {}

    actions = plan_album_sync(
        [col], resolved, state, client, share_with=["user-1"], skip_empty=False
    )

    assert len(actions) == 2
    assert actions[0].kind == "create"
    assert actions[1].kind == "share"
    assert actions[1].user_ids == ["user-1"]


@respx.mock
def test_apply_create(state: StateDB, client: ImmichClient) -> None:
    respx.post(f"{API}/albums").mock(
        return_value=httpx.Response(200, json={"id": "imm-abc"})
    )

    actions = [
        AlbumAction(
            kind="create",
            lr_collection_id=10,
            album_name="New",
            asset_ids=["a1"],
        ),
    ]
    apply_album_sync(actions, client, state)

    ownership = state.get_album_ownership(10)
    assert ownership is not None
    assert ownership["immich_album_id"] == "imm-abc"


@respx.mock
def test_apply_create_and_share(state: StateDB, client: ImmichClient) -> None:
    respx.post(f"{API}/albums").mock(
        return_value=httpx.Response(200, json={"id": "imm-abc"})
    )
    respx.put(f"{API}/albums/imm-abc/users").mock(
        return_value=httpx.Response(200, json={})
    )

    actions = [
        AlbumAction(
            kind="create",
            lr_collection_id=10,
            album_name="New",
        ),
        AlbumAction(
            kind="share",
            lr_collection_id=10,
            album_name="New",
            user_ids=["u1"],
        ),
    ]
    apply_album_sync(actions, client, state)

    assert respx.calls.call_count == 2


@respx.mock
def test_update_assets(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "imm-1", "Album")
    respx.get(f"{API}/albums/imm-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [{"id": "a1"}, {"id": "a2"}],
                "albumUsers": [],
            },
        )
    )

    col = _col(id=10, full_name="Album", relative_paths=["x.jpg", "y.jpg"])
    resolved = {"x.jpg": "a2", "y.jpg": "a3"}

    actions = plan_album_sync([col], resolved, state, client)

    kinds = {a.kind for a in actions}
    assert "add_assets" in kinds
    assert "remove_assets" in kinds

    add = next(a for a in actions if a.kind == "add_assets")
    remove = next(a for a in actions if a.kind == "remove_assets")
    assert add.asset_ids == ["a3"]
    assert remove.asset_ids == ["a1"]


@respx.mock
def test_rename_detection(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "imm-1", "OldName")
    respx.get(f"{API}/albums/imm-1").mock(
        return_value=httpx.Response(200, json={"assets": [], "albumUsers": []})
    )

    col = _col(id=10, full_name="NewName")
    actions = plan_album_sync([col], {}, state, client, skip_empty=False)

    assert any(a.kind == "rename" and a.album_name == "NewName" for a in actions)


@respx.mock
def test_format_change_triggers_rename(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "imm-1", "Travel/Japan")
    respx.get(f"{API}/albums/imm-1").mock(
        return_value=httpx.Response(200, json={"assets": [], "albumUsers": []})
    )

    col = _col(id=10, full_name="Travel/Japan")
    actions = plan_album_sync(
        [col], {}, state, client, skip_empty=False, album_name_format="{name}"
    )

    rename = [a for a in actions if a.kind == "rename"]
    assert len(rename) == 1
    assert rename[0].album_name == "Japan"
    assert rename[0].old_name == "Travel/Japan"


@respx.mock
def test_share_idempotent(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "imm-1", "Album")
    respx.get(f"{API}/albums/imm-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [],
                "albumUsers": [{"user": {"id": "u1"}, "role": "editor"}],
            },
        )
    )

    col = _col(id=10, full_name="Album")
    actions = plan_album_sync([col], {}, state, client, share_with=["u1"])

    assert not any(a.kind == "share" for a in actions)


@respx.mock
def test_threshold_blocks_delete(state: StateDB, client: ImmichClient) -> None:
    safety = SafetyConfig(delete_threshold=1)
    for i in range(3):
        state.upsert_album_ownership(100 + i, f"imm-{i}", f"Gone{i}")

    with pytest.raises(DeleteThresholdExceeded) as exc_info:
        plan_album_sync([], {}, state, client, safety=safety)
    assert exc_info.value.count == 3
    assert exc_info.value.threshold == 1


@respx.mock
def test_force_allows_delete(state: StateDB, client: ImmichClient) -> None:
    safety = SafetyConfig(delete_threshold=1)
    for i in range(3):
        state.upsert_album_ownership(100 + i, f"imm-{i}", f"Gone{i}")

    actions = plan_album_sync([], {}, state, client, safety=safety, force=True)

    assert len(actions) == 3
    assert all(a.kind == "delete" for a in actions)


@respx.mock
def test_no_delete_skips_deletes(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(100, "imm-x", "Gone")

    actions = plan_album_sync([], {}, state, client, no_delete=True)

    assert not any(a.kind == "delete" for a in actions)


@respx.mock
def test_disable_deletes_in_safety(state: StateDB, client: ImmichClient) -> None:
    safety = SafetyConfig(disable_deletes=True)
    state.upsert_album_ownership(100, "imm-x", "Gone")

    actions = plan_album_sync([], {}, state, client, safety=safety)

    assert not any(a.kind == "delete" for a in actions)


@respx.mock
def test_dry_run_no_mutations(state: StateDB, client: ImmichClient) -> None:
    col = _col(id=10, full_name="New", relative_paths=["a.jpg"])
    resolved = {"a.jpg": "asset-1"}

    actions = plan_album_sync([col], resolved, state, client)

    assert len(actions) == 1
    assert actions[0].kind == "create"
    assert state.get_album_ownership(10) is None
    assert respx.calls.call_count == 0


@respx.mock
def test_idempotency(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "imm-1", "Album")
    respx.get(f"{API}/albums/imm-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [{"id": "a1"}],
                "albumUsers": [],
            },
        )
    )

    col = _col(id=10, full_name="Album", relative_paths=["x.jpg"])
    resolved = {"x.jpg": "a1"}

    actions = plan_album_sync([col], resolved, state, client)

    assert len(actions) == 0


@respx.mock
def test_remove_percent_limit_blocks(state: StateDB, client: ImmichClient) -> None:
    safety = SafetyConfig(remove_percent_limit=50)
    state.upsert_album_ownership(10, "imm-1", "Album")
    respx.get(f"{API}/albums/imm-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [{"id": f"a{i}"} for i in range(10)],
                "albumUsers": [],
            },
        )
    )

    col = _col(id=10, full_name="Album", relative_paths=["x.jpg"])
    resolved = {"x.jpg": "a0"}

    with pytest.raises(RemoveLimitExceeded) as exc_info:
        plan_album_sync([col], resolved, state, client, safety=safety)
    assert exc_info.value.album_name == "Album"
    assert exc_info.value.percent > 50


@respx.mock
def test_remove_percent_limit_force(state: StateDB, client: ImmichClient) -> None:
    safety = SafetyConfig(remove_percent_limit=50)
    state.upsert_album_ownership(10, "imm-1", "Album")
    respx.get(f"{API}/albums/imm-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "assets": [{"id": f"a{i}"} for i in range(10)],
                "albumUsers": [],
            },
        )
    )

    col = _col(id=10, full_name="Album", relative_paths=["x.jpg"])
    resolved = {"x.jpg": "a0"}

    actions = plan_album_sync([col], resolved, state, client, safety=safety, force=True)

    assert any(a.kind == "remove_assets" for a in actions)


@respx.mock
def test_apply_full_lifecycle(state: StateDB, client: ImmichClient) -> None:
    respx.post(f"{API}/albums").mock(
        return_value=httpx.Response(200, json={"id": "imm-new"})
    )
    respx.patch(f"{API}/albums/imm-new").mock(return_value=httpx.Response(200, json={}))
    respx.put(f"{API}/albums/imm-new/assets").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.delete(url=f"{API}/albums/imm-old/assets").mock(
        return_value=httpx.Response(200, json=None)
    )
    respx.delete(url=f"{API}/albums/imm-old").mock(
        return_value=httpx.Response(200, json=None)
    )

    state.upsert_album_ownership(99, "imm-old", "OldAlbum")

    actions = [
        AlbumAction(
            kind="create",
            lr_collection_id=10,
            album_name="New",
            asset_ids=["a1"],
        ),
        AlbumAction(
            kind="rename",
            lr_collection_id=10,
            immich_album_id="imm-new",
            album_name="Renamed",
            old_name="New",
        ),
        AlbumAction(
            kind="add_assets",
            lr_collection_id=10,
            immich_album_id="imm-new",
            album_name="Renamed",
            asset_ids=["a2"],
        ),
        AlbumAction(
            kind="remove_assets",
            lr_collection_id=99,
            immich_album_id="imm-old",
            album_name="OldAlbum",
            asset_ids=["a3"],
        ),
        AlbumAction(
            kind="delete",
            lr_collection_id=99,
            immich_album_id="imm-old",
            album_name="OldAlbum",
        ),
    ]
    apply_album_sync(actions, client, state)

    assert state.get_album_ownership(10) is not None
    assert state.get_album_ownership(99) is None
    logs = state.get_audit_log()
    assert len(logs) == 5
