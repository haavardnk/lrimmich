from pathlib import Path

import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.utils.resolver import map_path, resolve_paths, spot_check_cache


@pytest.mark.parametrize(
    ("relative", "immich_library_path", "expected"),
    [
        ("2024/jan/IMG_001.jpg", "/external/", "/external/2024/jan/IMG_001.jpg"),
        ("a.jpg", "/ext/", "/ext/a.jpg"),
        ("a.jpg", "", "a.jpg"),
    ],
    ids=["nested", "simple", "empty-root"],
)
def test_map_path(relative: str, immich_library_path: str, expected: str) -> None:
    assert map_path(relative, immich_library_path) == expected


IMMICH_URL = "http://immich.test"
API = f"{IMMICH_URL}/api"


def _mock_folders(folders: list[str], assets: dict[str, list[dict[str, str]]]) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=folders)
    for folder, items in assets.items():
        respx.get(f"{API}/view/folder", params={"path": folder}).respond(
            json=[{"id": a["id"], "originalPath": a["originalPath"]} for a in items]
        )


@respx.mock
@pytest.mark.anyio
async def test_single_match(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext"],
        {"/ext": [{"id": "asset-1", "originalPath": "/ext/a.jpg"}]},
    )
    result, _ = await resolve_paths({"a.jpg"}, "/ext/", client)
    assert result == {"a.jpg": "asset-1"}


@respx.mock
@pytest.mark.anyio
async def test_ambiguous_match(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext/other", "/ext/2024"],
        {
            "/ext/other": [{"id": "wrong", "originalPath": "/ext/other/a.jpg"}],
            "/ext/2024": [{"id": "correct", "originalPath": "/ext/2024/a.jpg"}],
        },
    )
    result, _ = await resolve_paths({"2024/a.jpg"}, "/ext/", client)
    assert result == {"2024/a.jpg": "correct"}


@respx.mock
@pytest.mark.anyio
async def test_trashed_asset_filtered(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext"],
        {"/ext": [{"id": "trashed", "originalPath": "/ext/a.jpg", "isTrashed": True}]},
    )
    respx.get(f"{API}/view/folder", params={"path": "/ext"}).respond(
        json=[{"id": "trashed", "originalPath": "/ext/a.jpg", "isTrashed": True}]
    )
    result, _ = await resolve_paths({"a.jpg"}, "/ext/", client)
    assert result == {}


@respx.mock
@pytest.mark.anyio
async def test_unmatched(client: ImmichClient) -> None:
    _mock_folders(["/ext"], {"/ext": []})
    result, _ = await resolve_paths({"missing.jpg"}, "/ext/", client)
    assert result == {}


@respx.mock
@pytest.mark.anyio
async def test_irrelevant_folders_skipped(client: ImmichClient) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(
        json=["/ext/photos", "/other/videos"]
    )
    respx.get(f"{API}/view/folder", params={"path": "/ext/photos"}).respond(
        json=[{"id": "a1", "originalPath": "/ext/photos/a.jpg"}]
    )
    result, _ = await resolve_paths({"photos/a.jpg"}, "/ext/", client)
    assert result == {"photos/a.jpg": "a1"}


@respx.mock
@pytest.mark.anyio
async def test_same_filename_different_folders(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext/dir1", "/ext/dir2"],
        {
            "/ext/dir1": [{"id": "a1", "originalPath": "/ext/dir1/same.jpg"}],
            "/ext/dir2": [{"id": "a2", "originalPath": "/ext/dir2/same.jpg"}],
        },
    )
    result, _ = await resolve_paths({"dir1/same.jpg", "dir2/same.jpg"}, "/ext/", client)
    assert result == {"dir1/same.jpg": "a1", "dir2/same.jpg": "a2"}


@respx.mock
@pytest.mark.anyio
async def test_warm_cache_skips_api(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "cached-id", "a.jpg")
    result, _ = await resolve_paths({"a.jpg"}, "/ext/", client, state=state)
    assert result == {"a.jpg": "cached-id"}


@respx.mock
@pytest.mark.anyio
async def test_cache_miss_falls_through(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "cached-id", "a.jpg")
    _mock_folders(
        ["/ext"],
        {"/ext": [{"id": "new-id", "originalPath": "/ext/b.jpg"}]},
    )
    result, _ = await resolve_paths({"a.jpg", "b.jpg"}, "/ext/", client, state=state)
    assert result == {"a.jpg": "cached-id", "b.jpg": "new-id"}


@respx.mock
@pytest.mark.anyio
async def test_cache_ttl_expires_old_entries(
    client: ImmichClient, tmp_path: Path
) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "cached-id", "a.jpg")
    state._conn.execute(
        "UPDATE path_cache SET last_verified_at = last_verified_at - 999999"
    )
    _mock_folders(
        ["/ext"],
        {"/ext": [{"id": "fresh-id", "originalPath": "/ext/a.jpg"}]},
    )
    result, _ = await resolve_paths(
        {"a.jpg"}, "/ext/", client, max_cache_age=3600, state=state
    )
    assert result == {"a.jpg": "fresh-id"}


@respx.mock
@pytest.mark.anyio
async def test_resolve_returns_cache_hits(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "cached-id", "a.jpg")
    _mock_folders(["/ext"], {"/ext": [{"id": "b-id", "originalPath": "/ext/b.jpg"}]})
    _, hits = await resolve_paths({"a.jpg", "b.jpg"}, "/ext/", client, state=state)
    assert hits == {"a.jpg"}


@respx.mock
@pytest.mark.anyio
async def test_spot_check_valid(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "a1", "a.jpg")
    respx.get(f"{API}/assets/a1").respond(
        json={"id": "a1", "originalPath": "/ext/a.jpg"}
    )
    count = await spot_check_cache({"a.jpg": "a1"}, "/ext/", client, state, pct=100)
    assert count == 0
    assert state.get_all_cached_paths().get("a.jpg") == "a1"


@respx.mock
@pytest.mark.anyio
async def test_spot_check_invalid_path(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "a1", "a.jpg")
    respx.get(f"{API}/assets/a1").respond(
        json={"id": "a1", "originalPath": "/ext/moved.jpg"}
    )
    count = await spot_check_cache({"a.jpg": "a1"}, "/ext/", client, state, pct=100)
    assert count == 1
    assert "a.jpg" not in state.get_all_cached_paths()


@respx.mock
@pytest.mark.anyio
async def test_spot_check_trashed(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "a1", "a.jpg")
    respx.get(f"{API}/assets/a1").respond(
        json={"id": "a1", "originalPath": "/ext/a.jpg", "isTrashed": True}
    )
    count = await spot_check_cache({"a.jpg": "a1"}, "/ext/", client, state, pct=100)
    assert count == 1


@respx.mock
@pytest.mark.anyio
async def test_spot_check_404(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "gone", "a.jpg")
    respx.get(f"{API}/assets/gone").respond(status_code=404)
    count = await spot_check_cache({"a.jpg": "gone"}, "/ext/", client, state, pct=100)
    assert count == 1


def test_evict_stale_cache(tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("old.jpg", "a1", "old.jpg")
    state._conn.execute(
        "UPDATE path_cache SET last_verified_at = last_verified_at - 999999"
    )
    state.upsert_path_cache("new.jpg", "a2", "new.jpg")
    evicted = state.evict_stale_cache(3600)
    assert evicted == 1
    remaining = state.get_all_cached_paths()
    assert "old.jpg" not in remaining
    assert "new.jpg" in remaining
