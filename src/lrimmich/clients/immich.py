from typing import Any, Self

import httpx
import stamina

CHUNK_SIZE = 1000
MAX_RETRIES = 3
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class _RetryableStatusError(httpx.HTTPStatusError):
    pass


class ImmichClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/api",
            headers={"x-api-key": api_key},
            timeout=timeout,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @stamina.retry(on=_RetryableStatusError, attempts=MAX_RETRIES)
    def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        response = self._client.request(method, path, json=json, params=params)
        if response.status_code in RETRYABLE_STATUSES:
            raise _RetryableStatusError(
                message=f"{response.status_code}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def close(self) -> None:
        self._client.close()

    def server_about(self) -> dict[str, Any]:
        return self._request("GET", "/server/about")

    def server_config(self) -> dict[str, Any]:
        return self._request("GET", "/server/config")

    def get_albums(self) -> list[dict[str, Any]]:
        return self._request("GET", "/albums") or []

    def get_album(self, album_id: str) -> dict[str, Any]:
        return self._request("GET", f"/albums/{album_id}")

    def create_album(
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
        return self._request("POST", "/albums", payload)

    def update_album(self, album_id: str, **fields: Any) -> dict[str, Any]:
        return self._request("PATCH", f"/albums/{album_id}", fields)

    def delete_album(self, album_id: str) -> None:
        self._request("DELETE", f"/albums/{album_id}")

    def add_album_assets(
        self, album_id: str, asset_ids: list[str]
    ) -> list[dict[str, Any]]:
        if not asset_ids:
            return []
        return self._request("PUT", f"/albums/{album_id}/assets", {"ids": asset_ids})

    def remove_album_assets(self, album_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        self._request("DELETE", f"/albums/{album_id}/assets", {"ids": asset_ids})

    def add_album_users(self, album_id: str, user_ids: list[str]) -> None:
        if not user_ids:
            return
        album_users = [{"userId": uid, "role": "editor"} for uid in user_ids]
        try:
            self._request(
                "PUT",
                f"/albums/{album_id}/users",
                {"albumUsers": album_users},
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 400 and "already" in e.response.text.lower():
                return
            raise

    def search_metadata(
        self,
        filename: str | None = None,
        size: int = 250,
        max_results: int | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        page: int | str = 1
        while True:
            payload: dict[str, Any] = {"page": page, "size": size}
            if filename is not None:
                payload["originalFileName"] = filename
            resp = self._request(
                "POST",
                "/search/metadata",
                payload,
            )
            assets = resp.get("assets", {})
            items = assets.get("items", [])
            results.extend(items)
            if max_results is not None and len(results) >= max_results:
                return results[:max_results]
            next_page = assets.get("nextPage")
            if next_page is None:
                break
            page = next_page
        return results

    def bulk_update_assets(self, asset_ids: list[str], **fields: Any) -> None:
        if not asset_ids:
            return
        for i in range(0, len(asset_ids), CHUNK_SIZE):
            chunk = asset_ids[i : i + CHUNK_SIZE]
            self._request("PUT", "/assets", {"ids": chunk, **fields})

    def update_asset(self, asset_id: str, **fields: Any) -> dict[str, Any]:
        return self._request("PUT", f"/assets/{asset_id}", fields)

    def get_tags(self) -> list[dict[str, Any]]:
        return self._request("GET", "/tags") or []

    def create_tag(self, name: str) -> dict[str, Any]:
        return self._request("POST", "/tags", {"name": name})

    def tag_assets(self, tag_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        self._request("PUT", f"/tags/{tag_id}/assets", {"ids": asset_ids})

    def untag_assets(self, tag_id: str, asset_ids: list[str]) -> None:
        if not asset_ids:
            return
        self._request("DELETE", f"/tags/{tag_id}/assets", {"ids": asset_ids})

    def get_folder_paths(self) -> list[str]:
        return self._request("GET", "/view/folder/unique-paths") or []

    def get_folder_assets(self, path: str) -> list[dict[str, Any]]:
        return self._request("GET", "/view/folder", params={"path": path}) or []
