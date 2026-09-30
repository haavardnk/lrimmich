from typing import Any, Self

import httpx
import stamina

CHUNK_SIZE = 1000
SEARCH_PAGE_SIZE = 1000
MAX_RETRIES = 3
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class _RetryableStatusError(httpx.HTTPStatusError):
    pass


class ImmichClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api",
            headers={"x-api-key": api_key},
            timeout=timeout,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    @stamina.retry(on=_RetryableStatusError, attempts=MAX_RETRIES)
    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        response = await self._client.request(method, path, json=json, params=params)
        if response.status_code in RETRYABLE_STATUSES:
            raise _RetryableStatusError(
                message=f"{response.status_code}",
                request=response.request,
                response=response,
            )
        if response.is_error:
            raise httpx.HTTPStatusError(
                f"{response.status_code} for {method} {path}: {response.text[:500]}",
                request=response.request,
                response=response,
            )
        if not response.content:
            return None
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def server_about(self) -> dict[str, Any]:
        return await self._request("GET", "/server/about")

    async def get_albums(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/albums", params={"isOwned": "true"}) or []

    async def get_album_asset_ids(self, album_id: str) -> set[str]:
        asset_ids: set[str] = set()
        page: str | None = "1"
        while page:
            result = await self._request(
                "POST",
                "/search/metadata",
                {
                    "albumIds": [album_id],
                    "withDeleted": True,
                    "size": SEARCH_PAGE_SIZE,
                    "page": int(page),
                },
            )
            asset_ids.update(a["id"] for a in result["assets"]["items"])
            page = result["assets"]["nextPage"]
        return asset_ids

    async def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        return await self._request("GET", f"/assets/{asset_id}")

    async def create_album(
        self,
        name: str,
        asset_ids: list[str] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"albumName": name}
        if description:
            payload["description"] = description
        if asset_ids:
            payload["assetIds"] = asset_ids
        return await self._request("POST", "/albums", payload)

    async def update_album(self, album_id: str, **fields: Any) -> dict[str, Any]:
        return await self._request("PATCH", f"/albums/{album_id}", fields)

    async def delete_album(self, album_id: str) -> None:
        await self._request("DELETE", f"/albums/{album_id}")

    async def add_album_assets(
        self, album_id: str, asset_ids: list[str]
    ) -> list[dict[str, Any]]:
        if not asset_ids:
            return []
        return await self._request(
            "PUT", f"/albums/{album_id}/assets", {"ids": asset_ids}
        )

    async def remove_album_assets(self, album_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        await self._request("DELETE", f"/albums/{album_id}/assets", {"ids": asset_ids})

    async def add_album_users(self, album_id: str, user_ids: list[str]) -> None:
        if not user_ids:
            return
        album_users = [{"userId": uid, "role": "editor"} for uid in user_ids]
        try:
            await self._request(
                "PUT",
                f"/albums/{album_id}/users",
                {"albumUsers": album_users},
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "already" in e.response.text.lower():
                return
            raise

    async def bulk_update_assets(self, asset_ids: list[str], **fields: Any) -> None:
        if not asset_ids:
            return
        for i in range(0, len(asset_ids), CHUNK_SIZE):
            chunk = asset_ids[i : i + CHUNK_SIZE]
            await self._request("PATCH", "/assets", {"ids": chunk, **fields})

    async def get_tags(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/tags") or []

    async def create_tag(self, name: str) -> dict[str, Any]:
        return await self._request("POST", "/tags", {"name": name})

    async def tag_assets(self, tag_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        await self._request("PUT", f"/tags/{tag_id}/assets", {"ids": asset_ids})

    async def untag_assets(self, tag_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        await self._request("DELETE", f"/tags/{tag_id}/assets", {"ids": asset_ids})

    async def get_folder_paths(self) -> list[str]:
        return await self._request("GET", "/view/folder/unique-paths") or []

    async def get_folder_assets(self, path: str) -> list[dict[str, Any]]:
        return await self._request("GET", "/view/folder", params={"path": path}) or []

    async def get_stacks(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/stacks") or []

    async def create_stack(self, asset_ids: list[str]) -> dict[str, Any]:
        return await self._request("POST", "/stacks", {"assetIds": asset_ids})

    async def update_stack(
        self, stack_id: str, primary_asset_id: str
    ) -> dict[str, Any]:
        return await self._request(
            "PATCH", f"/stacks/{stack_id}", {"primaryAssetId": primary_asset_id}
        )

    async def delete_stack(self, stack_id: str) -> None:
        await self._request("DELETE", f"/stacks/{stack_id}")
