import httpx
import pytest
import respx

from lrimmich.immich import ImmichClient


@respx.mock
def test_server_about(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/server/about").mock(
        return_value=httpx.Response(200, json={"version": "1.100.0"})
    )
    result = client.server_about()
    assert result["version"] == "1.100.0"


@respx.mock
def test_server_config(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/server/config").mock(
        return_value=httpx.Response(200, json={"isInitialized": True})
    )
    result = client.server_config()
    assert result["isInitialized"] is True


@respx.mock
def test_get_albums(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/albums").mock(
        return_value=httpx.Response(200, json=[{"id": "a1", "albumName": "Test"}])
    )
    albums = client.get_albums()
    assert len(albums) == 1
    assert albums[0]["albumName"] == "Test"


@respx.mock
def test_get_album(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/albums/a1").mock(
        return_value=httpx.Response(200, json={"id": "a1", "assets": []})
    )
    album = client.get_album("a1")
    assert album["id"] == "a1"


@respx.mock
def test_create_album(client: ImmichClient, api_url: str) -> None:
    route = respx.post(f"{api_url}/albums").mock(
        return_value=httpx.Response(201, json={"id": "new1", "albumName": "New"})
    )
    result = client.create_album("New", asset_ids=["x1"])
    assert result["id"] == "new1"
    body = route.calls[0].request.content
    assert b"assetIds" in body


@respx.mock
def test_update_album(client: ImmichClient, api_url: str) -> None:
    respx.patch(f"{api_url}/albums/a1").mock(
        return_value=httpx.Response(200, json={"id": "a1", "albumName": "Renamed"})
    )
    result = client.update_album("a1", albumName="Renamed")
    assert result["albumName"] == "Renamed"


@respx.mock
def test_delete_album(client: ImmichClient, api_url: str) -> None:
    respx.delete(f"{api_url}/albums/a1").mock(return_value=httpx.Response(204))
    client.delete_album("a1")


@respx.mock
def test_add_album_assets(client: ImmichClient, api_url: str) -> None:
    respx.put(f"{api_url}/albums/a1/assets").mock(
        return_value=httpx.Response(200, json=[{"id": "x1", "success": True}])
    )
    result = client.add_album_assets("a1", ["x1"])
    assert result[0]["success"] is True


@respx.mock
def test_add_album_assets_empty(client: ImmichClient, api_url: str) -> None:
    result = client.add_album_assets("a1", [])
    assert result == []


@respx.mock
def test_remove_album_assets(client: ImmichClient, api_url: str) -> None:
    respx.delete(f"{api_url}/albums/a1/assets").mock(
        return_value=httpx.Response(200, json=[])
    )
    client.remove_album_assets("a1", ["x1"])


@respx.mock
def test_add_album_users_success(client: ImmichClient, api_url: str) -> None:
    respx.put(f"{api_url}/albums/a1/users").mock(
        return_value=httpx.Response(200, json={})
    )
    client.add_album_users("a1", ["u1"])


@respx.mock
def test_add_album_users_400_ignored(client: ImmichClient, api_url: str) -> None:
    respx.put(f"{api_url}/albums/a1/users").mock(return_value=httpx.Response(400))
    client.add_album_users("a1", ["u1"])


@respx.mock
def test_add_album_users_empty(client: ImmichClient, api_url: str) -> None:
    client.add_album_users("a1", [])


@respx.mock
def test_search_metadata(client: ImmichClient, api_url: str) -> None:
    respx.post(f"{api_url}/search/metadata").mock(
        return_value=httpx.Response(
            200, json={"assets": {"items": [{"id": "x1", "originalPath": "/a/b.jpg"}]}}
        )
    )
    results = client.search_metadata("b.jpg")
    assert len(results) == 1
    assert results[0]["id"] == "x1"


@respx.mock
def test_search_metadata_pagination(client: ImmichClient, api_url: str) -> None:
    page1 = [{"id": f"x{i}"} for i in range(250)]
    page2 = [{"id": "x250"}]
    route = respx.post(f"{api_url}/search/metadata")
    route.side_effect = [
        httpx.Response(200, json={"assets": {"items": page1}}),
        httpx.Response(200, json={"assets": {"items": page2}}),
    ]
    results = client.search_metadata("file.jpg")
    assert len(results) == 251


@respx.mock
def test_bulk_update_assets(client: ImmichClient, api_url: str) -> None:
    route = respx.put(f"{api_url}/assets").mock(return_value=httpx.Response(204))
    client.bulk_update_assets(["x1", "x2"], isFavorite=True)
    assert route.call_count == 1


@respx.mock
def test_bulk_update_assets_chunking(client: ImmichClient, api_url: str) -> None:
    route = respx.put(f"{api_url}/assets").mock(return_value=httpx.Response(204))
    ids = [f"x{i}" for i in range(2500)]
    client.bulk_update_assets(ids, isFavorite=True)
    assert route.call_count == 3


@respx.mock
def test_bulk_update_assets_empty(client: ImmichClient, api_url: str) -> None:
    client.bulk_update_assets([], isFavorite=False)


@respx.mock
def test_update_asset(client: ImmichClient, api_url: str) -> None:
    respx.put(f"{api_url}/assets/x1").mock(
        return_value=httpx.Response(200, json={"id": "x1"})
    )
    result = client.update_asset("x1", isFavorite=True)
    assert result["id"] == "x1"


@respx.mock
def test_retry_on_429(client: ImmichClient, api_url: str) -> None:
    route = respx.get(f"{api_url}/server/about")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={"version": "1.0"}),
    ]
    result = client.server_about()
    assert result["version"] == "1.0"
    assert route.call_count == 2


@respx.mock
def test_retry_on_500(client: ImmichClient, api_url: str) -> None:
    route = respx.get(f"{api_url}/server/about")
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(200, json={"version": "1.0"}),
    ]
    result = client.server_about()
    assert result["version"] == "1.0"
    assert route.call_count == 2


@respx.mock
def test_retry_exhausted_raises(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/server/about").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        client.server_about()


@respx.mock
def test_401_not_retried(client: ImmichClient, api_url: str) -> None:
    route = respx.get(f"{api_url}/server/about").mock(return_value=httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError):
        client.server_about()
    assert route.call_count == 1


@respx.mock
def test_get_tags(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/tags").mock(
        return_value=httpx.Response(200, json=[{"id": "t1", "name": "lr:color:red"}])
    )
    tags = client.get_tags()
    assert tags[0]["name"] == "lr:color:red"


@respx.mock
def test_create_tag(client: ImmichClient, api_url: str) -> None:
    respx.post(f"{api_url}/tags").mock(
        return_value=httpx.Response(201, json={"id": "t1", "name": "lr:color:red"})
    )
    tag = client.create_tag("lr:color:red")
    assert tag["id"] == "t1"


@respx.mock
def test_tag_assets(client: ImmichClient, api_url: str) -> None:
    route = respx.put(f"{api_url}/tags/t1/assets").mock(
        return_value=httpx.Response(200, json=[])
    )
    client.tag_assets("t1", ["x1", "x2"])
    assert route.call_count == 1


@respx.mock
def test_tag_assets_empty(client: ImmichClient, api_url: str) -> None:
    client.tag_assets("t1", [])
