import json

import httpx
import respx

API = "http://immich.test/api"


def mock_albums(
    albums: dict[str, list[str]],
    users: dict[str, list[str]] | None = None,
) -> respx.Route:
    shared = users or {}

    def _list(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": album_id,
                    "albumName": album_id,
                    "assetCount": len(asset_ids),
                    "albumUsers": [
                        {"user": {"id": uid}, "role": "editor"}
                        for uid in shared.get(album_id, [])
                    ],
                }
                for album_id, asset_ids in albums.items()
            ],
        )

    def _search(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        items = [{"id": aid} for aid in albums[body["albumIds"][0]]]
        return httpx.Response(200, json={"assets": {"items": items, "nextPage": None}})

    respx.get(f"{API}/albums").mock(side_effect=_list)
    return respx.post(f"{API}/search/metadata").mock(side_effect=_search)
