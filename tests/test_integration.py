from pathlib import Path

import httpx
import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.orchestrator import run_sync
from lrimmich.utils.config import Config
from tests.fixtures.catalog_factory import CatalogBuilder

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    builder = CatalogBuilder(tmp_path / "test.lrcat")
    builder.add_collection(1, "Vacation")
    builder.add_image(1, "beach.jpg", "photos/", pick=1)
    builder.add_image(2, "mountain.jpg", "photos/")
    builder.add_collection_image(1, 1)
    builder.add_collection_image(1, 2)
    return builder.build()


@pytest.fixture()
def cfg(catalog: Path) -> Config:
    return Config(
        catalogs=[{"catalog": catalog}],
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_path": ""},
        cache={"spot_check_pct": 0},
    )


def _mock_folders(asset_map: dict[str, str]) -> None:
    folder_assets = [
        {"id": aid, "originalPath": f"photos/{fn}"} for fn, aid in asset_map.items()
    ]
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(json=folder_assets)
    respx.get(f"{API}/tags").respond(json=[])


def _mock_album_crud() -> dict[str, list[dict[str, str]]]:
    albums: dict[str, list[dict[str, str]]] = {}

    def create_handler(request: httpx.Request) -> httpx.Response:
        import json

        data = json.loads(request.content.decode())
        album_id = f"imm-{len(albums) + 1}"
        asset_ids = data.get("assetIds", [])
        albums[album_id] = [{"id": aid} for aid in asset_ids]
        return httpx.Response(200, json={"id": album_id})

    def get_handler(request: httpx.Request, route: respx.Route) -> httpx.Response:
        album_id = str(request.url).split("/albums/")[-1]
        assets = albums.get(album_id, [])
        return httpx.Response(
            200,
            json={
                "assets": assets,
                "albumUsers": [],
            },
        )

    respx.post(f"{API}/albums").mock(side_effect=create_handler)
    respx.get(url__regex=rf"{API}/albums/imm-\d+$").mock(side_effect=get_handler)
    respx.patch(url__regex=rf"{API}/albums/imm-\d+$").respond(json={"id": "imm-1"})
    respx.put(f"{API}/assets").mock(return_value=httpx.Response(200, json=None))
    respx.get(f"{API}/tags").respond(json=[])
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "created"})
    return albums


@respx.mock
@pytest.mark.anyio
async def test_status_then_sync_idempotency(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    _mock_folders({"beach.jpg": "a1", "mountain.jpg": "a2"})
    _mock_album_crud()

    status1 = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)
    assert status1.has_drift
    assert status1.albums_created == 1

    await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    status2 = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)
    assert status2.albums_created == 0
    assert status2.albums_renamed == 0
    assert status2.albums_deleted == 0
    assert status2.assets_added == 0
    assert status2.assets_removed == 0


@respx.mock
@pytest.mark.anyio
async def test_drift_detection(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    _mock_folders({"beach.jpg": "a1", "mountain.jpg": "a2"})
    _mock_album_crud()

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)

    assert summary.has_drift
    assert summary.albums_created > 0
    assert summary.favorites.favorited > 0


@respx.mock
@pytest.mark.anyio
async def test_audit_log_entries(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    _mock_folders({"beach.jpg": "a1", "mountain.jpg": "a2"})
    _mock_album_crud()

    await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    logs = state.get_audit_log()
    actions = {log["action"] for log in logs}
    assert "create_album" in actions
    assert "sync_favorites" in actions


@respx.mock
@pytest.mark.anyio
async def test_sync_json_shape_stable(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    _mock_folders({})

    s1 = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)
    s2 = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)

    d1 = s1.to_dict()
    d2 = s2.to_dict()
    assert set(d1.keys()) == set(d2.keys())
    assert d1 == d2


@respx.mock
@pytest.mark.anyio
async def test_multi_domain_orchestration(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    _mock_folders({"beach.jpg": "a1", "mountain.jpg": "a2"})
    _mock_album_crud()

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    assert not summary.errors
    assert state.get_album_ownership(1) is not None
    logs = state.get_audit_log()
    assert len(logs) >= 2
