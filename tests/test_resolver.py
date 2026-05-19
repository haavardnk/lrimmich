from pathlib import Path

import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.utils.resolver import map_path, resolve_paths


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
    result = await resolve_paths({"a.jpg"}, "/ext/", client)
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
    result = await resolve_paths({"2024/a.jpg"}, "/ext/", client)
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
    result = await resolve_paths({"a.jpg"}, "/ext/", client)
    assert result == {}


@respx.mock
@pytest.mark.anyio
async def test_unmatched(client: ImmichClient) -> None:
    _mock_folders(["/ext"], {"/ext": []})
    result = await resolve_paths({"missing.jpg"}, "/ext/", client)
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
    result = await resolve_paths({"photos/a.jpg"}, "/ext/", client)
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
    result = await resolve_paths({"dir1/same.jpg", "dir2/same.jpg"}, "/ext/", client)
    assert result == {"dir1/same.jpg": "a1", "dir2/same.jpg": "a2"}


@respx.mock
@pytest.mark.anyio
async def test_warm_cache_skips_api(client: ImmichClient, tmp_path: Path) -> None:
    state = StateDB(tmp_path / "state.db")
    state.upsert_path_cache("a.jpg", "cached-id", "a.jpg")
    result = await resolve_paths({"a.jpg"}, "/ext/", client, state=state)
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
    result = await resolve_paths({"a.jpg", "b.jpg"}, "/ext/", client, state=state)
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
    result = await resolve_paths(
        {"a.jpg"}, "/ext/", client, state=state, max_cache_age=3600
    )
    assert result == {"a.jpg": "fresh-id"}
