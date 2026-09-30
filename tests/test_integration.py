import json
from pathlib import Path

import httpx
import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.orchestrator import run_sync
from lrimmich.utils.config import Config
from tests.fixtures.catalog_factory import CatalogBuilder
from tests.fixtures.immich_api import mock_albums

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
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_paths": [""]},
        cache={"spot_check_pct": 0},
    )


def _mock_folders(asset_map: dict[str, str]) -> None:
    folder_assets = [
        {"id": aid, "originalPath": f"photos/{fn}"} for fn, aid in asset_map.items()
    ]
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(json=folder_assets)
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])


def _mock_album_crud() -> dict[str, list[str]]:
    albums: dict[str, list[str]] = {}

    def create_handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content.decode())
        album_id = f"imm-{len(albums) + 1}"
        albums[album_id] = data.get("assetIds", [])
        return httpx.Response(200, json={"id": album_id})

    respx.post(f"{API}/albums").mock(side_effect=create_handler)
    mock_albums(albums)
    respx.patch(url__regex=rf"{API}/albums/imm-\d+$").respond(json={"id": "imm-1"})
    respx.patch(f"{API}/assets").mock(return_value=httpx.Response(200, json=None))
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


@respx.mock
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("sync", "expected"),
    [
        ({}, ["lr:color:red", "lr:keyword:Sea"]),
        (
            {"color_tags": {"Red": "Portfolio"}, "color_prefix": None},
            ["Portfolio", "lr:keyword:Sea"],
        ),
    ],
)
async def test_creates_tags_only_for_synced_assets(
    tmp_path: Path,
    client: ImmichClient,
    state: StateDB,
    sync: dict[str, object],
    expected: list[str],
) -> None:
    builder = CatalogBuilder(tmp_path / "tags.lrcat")
    builder.add_collection(1, "Vacation")
    builder.add_image(1, "beach.jpg", "photos/", color_labels="Red")
    builder.add_image(2, "city.jpg", "photos/", color_labels="Blue")
    builder.add_keyword(1, "Sea").add_keyword(2, "Street")
    builder.add_keyword_image(1, 1).add_keyword_image(2, 2)
    builder.add_collection_image(1, 1)
    cfg = Config(
        catalogs=[{"catalog": builder.build()}],
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_paths": [""]},
        cache={"spot_check_pct": 0},
        sync=sync,
    )
    _mock_folders({"beach.jpg": "a1", "city.jpg": "a2"})
    _mock_album_crud()
    created = respx.post(f"{API}/tags").mock(
        side_effect=lambda request: httpx.Response(
            200, json={"id": json.loads(request.content)["name"]}
        )
    )
    respx.put(url__regex=rf"{API}/tags/.*/assets").respond(json=[])

    summary = await run_sync(cfg, cfg.catalogs[0], client, state)

    assert not summary.errors
    names = sorted(json.loads(c.request.content)["name"] for c in created.calls)
    assert names == expected
