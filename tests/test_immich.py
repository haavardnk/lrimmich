import httpx
import pytest
import respx

from lrimmich.clients.immich import ImmichClient


@respx.mock
@pytest.mark.anyio
async def test_server_about(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/server/about").mock(
        return_value=httpx.Response(200, json={"version": "1.100.0"})
    )
    result = await client.server_about()
    assert result["version"] == "1.100.0"


@respx.mock
@pytest.mark.anyio
async def test_server_config(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/server/config").mock(
        return_value=httpx.Response(200, json={"isInitialized": True})
    )
    result = await client.server_config()
    assert result["isInitialized"] is True


@respx.mock
@pytest.mark.anyio
async def test_get_albums(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/albums").mock(
        return_value=httpx.Response(200, json=[{"id": "a1", "albumName": "Test"}])
    )
    albums = await client.get_albums()
    assert len(albums) == 1
    assert albums[0]["albumName"] == "Test"


@respx.mock
@pytest.mark.anyio
async def test_get_album(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/albums/a1").mock(
        return_value=httpx.Response(200, json={"id": "a1", "assets": []})
    )
    album = await client.get_album("a1")
    assert album["id"] == "a1"


@respx.mock
@pytest.mark.anyio
async def test_create_album(client: ImmichClient, api_url: str) -> None:
    route = respx.post(f"{api_url}/albums").mock(
        return_value=httpx.Response(201, json={"id": "new1", "albumName": "New"})
    )
    result = await client.create_album("New", asset_ids=["x1"])
    assert result["id"] == "new1"
    body = route.calls[0].request.content
    assert b"assetIds" in body


@respx.mock
@pytest.mark.anyio
async def test_update_album(client: ImmichClient, api_url: str) -> None:
    respx.patch(f"{api_url}/albums/a1").mock(
        return_value=httpx.Response(200, json={"id": "a1", "albumName": "Renamed"})
    )
    result = await client.update_album("a1", albumName="Renamed")
    assert result["albumName"] == "Renamed"


@respx.mock
@pytest.mark.anyio
async def test_delete_album(client: ImmichClient, api_url: str) -> None:
    respx.delete(f"{api_url}/albums/a1").mock(return_value=httpx.Response(204))
    await client.delete_album("a1")


@respx.mock
@pytest.mark.anyio
async def test_add_album_assets(client: ImmichClient, api_url: str) -> None:
    respx.put(f"{api_url}/albums/a1/assets").mock(
        return_value=httpx.Response(200, json=[{"id": "x1", "success": True}])
    )
    result = await client.add_album_assets("a1", ["x1"])
    assert result[0]["success"] is True


@respx.mock
@pytest.mark.anyio
async def test_add_album_assets_empty(client: ImmichClient) -> None:
    result = await client.add_album_assets("a1", [])
    assert result == []


@respx.mock
@pytest.mark.anyio
async def test_remove_album_assets(client: ImmichClient, api_url: str) -> None:
    respx.delete(f"{api_url}/albums/a1/assets").mock(
        return_value=httpx.Response(200, json=[])
    )
    await client.remove_album_assets("a1", ["x1"])


@respx.mock
@pytest.mark.anyio
async def test_add_album_users_success(client: ImmichClient, api_url: str) -> None:
    respx.put(f"{api_url}/albums/a1/users").mock(
        return_value=httpx.Response(200, json={})
    )
    await client.add_album_users("a1", ["u1"])


@respx.mock
@pytest.mark.anyio
async def test_add_album_users_already_added_ignored(
    client: ImmichClient, api_url: str
) -> None:
    respx.put(f"{api_url}/albums/a1/users").mock(
        return_value=httpx.Response(400, text="User already added to album")
    )
    await client.add_album_users("a1", ["u1"])


@respx.mock
@pytest.mark.anyio
async def test_add_album_users_400_other_raises(
    client: ImmichClient, api_url: str
) -> None:
    respx.put(f"{api_url}/albums/a1/users").mock(
        return_value=httpx.Response(400, text="Malformed payload")
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.add_album_users("a1", ["u1"])


@respx.mock
@pytest.mark.anyio
async def test_add_album_users_empty(client: ImmichClient) -> None:
    await client.add_album_users("a1", [])


@respx.mock
@pytest.mark.anyio
async def test_search_metadata(client: ImmichClient, api_url: str) -> None:
    respx.post(f"{api_url}/search/metadata").mock(
        return_value=httpx.Response(
            200, json={"assets": {"items": [{"id": "x1", "originalPath": "/a/b.jpg"}]}}
        )
    )
    results = await client.search_metadata("b.jpg")
    assert len(results) == 1
    assert results[0]["id"] == "x1"


@respx.mock
@pytest.mark.anyio
async def test_search_metadata_pagination(client: ImmichClient, api_url: str) -> None:
    page1 = [{"id": f"x{i}"} for i in range(250)]
    page2 = [{"id": "x250"}]
    route = respx.post(f"{api_url}/search/metadata")
    route.side_effect = [
        httpx.Response(200, json={"assets": {"items": page1, "nextPage": "2"}}),
        httpx.Response(200, json={"assets": {"items": page2}}),
    ]
    results = await client.search_metadata("file.jpg")
    assert len(results) == 251


@respx.mock
@pytest.mark.anyio
async def test_bulk_update_assets(client: ImmichClient, api_url: str) -> None:
    route = respx.put(f"{api_url}/assets").mock(return_value=httpx.Response(204))
    await client.bulk_update_assets(["x1", "x2"], isFavorite=True)
    assert route.call_count == 1


@respx.mock
@pytest.mark.anyio
async def test_bulk_update_assets_chunking(client: ImmichClient, api_url: str) -> None:
    route = respx.put(f"{api_url}/assets").mock(return_value=httpx.Response(204))
    ids = [f"x{i}" for i in range(2500)]
    await client.bulk_update_assets(ids, isFavorite=True)
    assert route.call_count == 3


@respx.mock
@pytest.mark.anyio
async def test_bulk_update_assets_empty(client: ImmichClient) -> None:
    await client.bulk_update_assets([], isFavorite=False)


@respx.mock
@pytest.mark.anyio
async def test_update_asset(client: ImmichClient, api_url: str) -> None:
    respx.put(f"{api_url}/assets/x1").mock(
        return_value=httpx.Response(200, json={"id": "x1"})
    )
    result = await client.update_asset("x1", isFavorite=True)
    assert result["id"] == "x1"


@respx.mock
@pytest.mark.anyio
@pytest.mark.parametrize("status", [429, 500, 502, 503])
async def test_retry_on_transient_error(
    status: int, client: ImmichClient, api_url: str
) -> None:
    route = respx.get(f"{api_url}/server/about")
    route.side_effect = [
        httpx.Response(status),
        httpx.Response(200, json={"version": "1.0"}),
    ]
    result = await client.server_about()
    assert result["version"] == "1.0"
    assert route.call_count == 2


@respx.mock
@pytest.mark.anyio
async def test_retry_exhausted_raises(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/server/about").mock(return_value=httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await client.server_about()


@respx.mock
@pytest.mark.anyio
async def test_401_not_retried(client: ImmichClient, api_url: str) -> None:
    route = respx.get(f"{api_url}/server/about").mock(return_value=httpx.Response(401))
    with pytest.raises(httpx.HTTPStatusError):
        await client.server_about()
    assert route.call_count == 1


@respx.mock
@pytest.mark.anyio
async def test_get_tags(client: ImmichClient, api_url: str) -> None:
    respx.get(f"{api_url}/tags").mock(
        return_value=httpx.Response(200, json=[{"id": "t1", "name": "lr:color:red"}])
    )
    tags = await client.get_tags()
    assert tags[0]["name"] == "lr:color:red"


@respx.mock
@pytest.mark.anyio
async def test_create_tag(client: ImmichClient, api_url: str) -> None:
    respx.post(f"{api_url}/tags").mock(
        return_value=httpx.Response(201, json={"id": "t1", "name": "lr:color:red"})
    )
    tag = await client.create_tag("lr:color:red")
    assert tag["id"] == "t1"


@respx.mock
@pytest.mark.anyio
async def test_tag_assets(client: ImmichClient, api_url: str) -> None:
    route = respx.put(f"{api_url}/tags/t1/assets").mock(
        return_value=httpx.Response(200, json=[])
    )
    await client.tag_assets("t1", ["x1", "x2"])
    assert route.call_count == 1


@respx.mock
@pytest.mark.anyio
async def test_tag_assets_empty(client: ImmichClient) -> None:
    await client.tag_assets("t1", [])


@respx.mock
@pytest.mark.anyio
async def test_get_folder_assets_special_chars(
    client: ImmichClient, api_url: str
) -> None:
    route = respx.get(f"{api_url}/view/folder").mock(
        return_value=httpx.Response(
            200, json=[{"id": "a1", "originalPath": "/lib/a&b#c"}]
        )
    )
    result = await client.get_folder_assets("/lib/a&b#c")
    assert result[0]["id"] == "a1"
    request = route.calls[0].request
    assert "path=%2Flib%2Fa%26b%23c" in str(request.url)
