import pytest
import respx

from lrimmich.config import PathMapping
from lrimmich.immich import ImmichClient
from lrimmich.resolver import map_path, resolve_paths


@pytest.mark.parametrize(
    ("relative", "path_map", "expected"),
    [
        (
            "2024/jan/IMG_001.jpg",
            [PathMapping(lr_path="2024/", immich_path="/external/2024/")],
            "/external/2024/jan/IMG_001.jpg",
        ),
        (
            "other/file.jpg",
            [PathMapping(lr_path="raw/", immich_path="/external/raw/")],
            "other/file.jpg",
        ),
    ],
    ids=["mapped", "unmapped"],
)
def test_map_path(relative: str, path_map: list[PathMapping], expected: str) -> None:
    assert map_path(relative, path_map) == expected


def test_map_path_multi_root() -> None:
    path_map = [
        PathMapping(lr_path="raw/", immich_path="/external/raw/"),
        PathMapping(lr_path="jpeg/", immich_path="/external/jpeg/"),
    ]
    assert map_path("raw/a.jpg", path_map) == "/external/raw/a.jpg"
    assert map_path("jpeg/b.jpg", path_map) == "/external/jpeg/b.jpg"
    assert map_path("other/c.jpg", path_map) == "other/c.jpg"


IMMICH_URL = "http://immich.test"
API = f"{IMMICH_URL}/api"


def _mock_folders(folders: list[str], assets: dict[str, list[dict[str, str]]]) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=folders)
    for folder, items in assets.items():
        respx.get(f"{API}/view/folder", params={"path": folder}).respond(
            json=[{"id": a["id"], "originalPath": a["originalPath"]} for a in items]
        )


@respx.mock
def test_single_match(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext"],
        {"/ext": [{"id": "asset-1", "originalPath": "/ext/a.jpg"}]},
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"a.jpg"}, path_map, client)
    assert result == {"a.jpg": "asset-1"}


@respx.mock
def test_ambiguous_match(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext/other", "/ext/2024"],
        {
            "/ext/other": [{"id": "wrong", "originalPath": "/ext/other/a.jpg"}],
            "/ext/2024": [{"id": "correct", "originalPath": "/ext/2024/a.jpg"}],
        },
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"2024/a.jpg"}, path_map, client)
    assert result == {"2024/a.jpg": "correct"}


@respx.mock
def test_trashed_asset_filtered(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext"],
        {"/ext": [{"id": "trashed", "originalPath": "/ext/a.jpg", "isTrashed": True}]},
    )
    respx.get(f"{API}/view/folder", params={"path": "/ext"}).respond(
        json=[{"id": "trashed", "originalPath": "/ext/a.jpg", "isTrashed": True}]
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"a.jpg"}, path_map, client)
    assert result == {}


@respx.mock
def test_unmatched(client: ImmichClient) -> None:
    _mock_folders(["/ext"], {"/ext": []})
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"missing.jpg"}, path_map, client)
    assert result == {}


@respx.mock
def test_multi_root_resolve(client: ImmichClient) -> None:
    _mock_folders(
        ["/raw", "/jpeg"],
        {
            "/raw": [{"id": "a1", "originalPath": "/raw/photo.jpg"}],
            "/jpeg": [{"id": "a2", "originalPath": "/jpeg/render.jpg"}],
        },
    )
    path_map = [
        PathMapping(lr_path="raw/", immich_path="/raw/"),
        PathMapping(lr_path="jpeg/", immich_path="/jpeg/"),
    ]
    result = resolve_paths({"raw/photo.jpg", "jpeg/render.jpg"}, path_map, client)
    assert result == {"raw/photo.jpg": "a1", "jpeg/render.jpg": "a2"}


@respx.mock
def test_irrelevant_folders_skipped(client: ImmichClient) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(
        json=["/ext/photos", "/other/videos"]
    )
    respx.get(f"{API}/view/folder", params={"path": "/ext/photos"}).respond(
        json=[{"id": "a1", "originalPath": "/ext/photos/a.jpg"}]
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"photos/a.jpg"}, path_map, client)
    assert result == {"photos/a.jpg": "a1"}


@respx.mock
def test_same_filename_different_folders(client: ImmichClient) -> None:
    _mock_folders(
        ["/ext/dir1", "/ext/dir2"],
        {
            "/ext/dir1": [{"id": "a1", "originalPath": "/ext/dir1/same.jpg"}],
            "/ext/dir2": [{"id": "a2", "originalPath": "/ext/dir2/same.jpg"}],
        },
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"dir1/same.jpg", "dir2/same.jpg"}, path_map, client)
    assert result == {"dir1/same.jpg": "a1", "dir2/same.jpg": "a2"}
