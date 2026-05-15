import httpx
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


@respx.mock
def test_single_match(client: ImmichClient, base_url: str) -> None:
    respx.post(f"{base_url}/api/search/metadata").respond(
        json={
            "assets": {
                "items": [
                    {
                        "id": "asset-1",
                        "originalPath": "/ext/a.jpg",
                        "isTrashed": False,
                    }
                ]
            }
        }
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"a.jpg"}, path_map, client)
    assert result == {"a.jpg": "asset-1"}


@respx.mock
def test_ambiguous_match(client: ImmichClient, base_url: str) -> None:
    respx.post(f"{base_url}/api/search/metadata").respond(
        json={
            "assets": {
                "items": [
                    {
                        "id": "wrong",
                        "originalPath": "/ext/other/a.jpg",
                        "isTrashed": False,
                    },
                    {
                        "id": "correct",
                        "originalPath": "/ext/2024/a.jpg",
                        "isTrashed": False,
                    },
                ]
            }
        }
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"2024/a.jpg"}, path_map, client)
    assert result == {"2024/a.jpg": "correct"}


@respx.mock
def test_trashed_asset_filtered(client: ImmichClient, base_url: str) -> None:
    respx.post(f"{base_url}/api/search/metadata").respond(
        json={
            "assets": {
                "items": [
                    {
                        "id": "trashed",
                        "originalPath": "/ext/a.jpg",
                        "isTrashed": True,
                    }
                ]
            }
        }
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"a.jpg"}, path_map, client)
    assert result == {}


@respx.mock
def test_unmatched(client: ImmichClient, base_url: str) -> None:
    respx.post(f"{base_url}/api/search/metadata").respond(
        json={"assets": {"items": []}}
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"missing.jpg"}, path_map, client)
    assert result == {}


@respx.mock
def test_multi_root_resolve(client: ImmichClient, base_url: str) -> None:
    def _respond(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "photo.jpg" in body:
            return httpx.Response(
                200,
                json={
                    "assets": {
                        "items": [
                            {
                                "id": "a1",
                                "originalPath": "/raw/photo.jpg",
                                "isTrashed": False,
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "assets": {
                    "items": [
                        {
                            "id": "a2",
                            "originalPath": "/jpeg/render.jpg",
                            "isTrashed": False,
                        }
                    ]
                }
            },
        )

    respx.post(f"{base_url}/api/search/metadata").mock(side_effect=_respond)
    path_map = [
        PathMapping(lr_path="raw/", immich_path="/raw/"),
        PathMapping(lr_path="jpeg/", immich_path="/jpeg/"),
    ]
    result = resolve_paths({"raw/photo.jpg", "jpeg/render.jpg"}, path_map, client)
    assert result == {"raw/photo.jpg": "a1", "jpeg/render.jpg": "a2"}


@respx.mock
def test_deduplicates_filename_searches(client: ImmichClient, base_url: str) -> None:
    route = respx.post(f"{base_url}/api/search/metadata")
    route.respond(
        json={
            "assets": {
                "items": [
                    {
                        "id": "a1",
                        "originalPath": "/ext/dir1/same.jpg",
                        "isTrashed": False,
                    },
                    {
                        "id": "a2",
                        "originalPath": "/ext/dir2/same.jpg",
                        "isTrashed": False,
                    },
                ]
            }
        }
    )
    path_map = [PathMapping(lr_path="", immich_path="/ext/")]
    result = resolve_paths({"dir1/same.jpg", "dir2/same.jpg"}, path_map, client)
    assert result == {"dir1/same.jpg": "a1", "dir2/same.jpg": "a2"}
    assert route.call_count == 1
