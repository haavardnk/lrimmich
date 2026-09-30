import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.orchestrator import run_multi_sync, run_sync
from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.config import Config
from tests.fixtures.catalog_factory import CatalogBuilder
from tests.fixtures.immich_api import mock_albums

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    builder = CatalogBuilder(tmp_path / "test.lrcat")
    builder.add_collection(1, "Travel")
    builder.add_image(1, "sunset.jpg", "photos/", pick=1)
    builder.add_collection_image(1, 1)
    return builder.build()


@pytest.fixture()
def cfg(catalog: Path) -> Config:
    return Config(
        catalogs=[{"catalog": catalog}],
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_paths": [""]},
        cache={"spot_check_pct": 0},
    )


@respx.mock
@pytest.mark.anyio
async def test_dry_run_no_mutations(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "created"})

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)

    assert summary.albums_created == 1
    assert summary.favorites.favorited == 1
    assert not summary.errors
    create_calls = [
        c
        for c in respx.calls
        if c.request.method == "POST" and "/albums" in str(c.request.url)
    ]
    assert len(create_calls) == 0


@respx.mock
@pytest.mark.anyio
async def test_json_shape(cfg: Config, client: ImmichClient, state: StateDB) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=[])
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)
    d = summary.to_dict()

    assert "albums_created" in d
    assert "favorites" in d
    assert "errors" in d


@respx.mock
@pytest.mark.anyio
async def test_status_stable(cfg: Config, client: ImmichClient, state: StateDB) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=[])
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])

    s1 = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)
    s2 = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)

    assert s1.to_dict() == s2.to_dict()


@respx.mock
@pytest.mark.anyio
async def test_partial_failure(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=[])
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])
    cfg.sync.albums = True
    cfg.sync.favorites = True

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)

    assert isinstance(summary, SyncSummary)


def test_summary_no_drift() -> None:
    s = SyncSummary()
    assert not s.has_drift


def test_summary_has_drift() -> None:
    s = SyncSummary(albums_created=1)
    assert s.has_drift


@respx.mock
@pytest.mark.anyio
async def test_skip_sync_when_catalog_unchanged(
    cfg: Config, client: ImmichClient, state: StateDB, catalog: Path
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.post(f"{API}/albums").respond(json={"id": "alb1"})
    respx.patch(f"{API}/assets").respond(json=[])
    respx.patch(url__regex=rf"{API}/albums/.*").respond(json={"id": "alb1"})

    await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    respx.reset()

    summary = await run_sync(cfg, cfg.catalogs[0], client, state)

    assert not summary.has_drift


@respx.mock
@pytest.mark.anyio
async def test_dry_run_ignores_fingerprint(
    cfg: Config, client: ImmichClient, state: StateDB, catalog: Path
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    albums: dict[str, list[str]] = {}
    mock_albums(albums)
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.post(f"{API}/albums").respond(json={"id": "alb1"})
    respx.patch(f"{API}/assets").respond(json=[])
    respx.patch(url__regex=rf"{API}/albums/.*").respond(json={"id": "alb1"})

    await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    albums["alb1"] = []

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)

    assert not summary.skipped_unchanged
    assert summary.assets_added == 1


@respx.mock
@pytest.mark.anyio
async def test_collection_move_is_detected(
    cfg: Config, client: ImmichClient, state: StateDB, catalog: Path
) -> None:
    cfg.safety.remove_percent_limit = 100
    cfg.sync.skip_empty = False
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.post(f"{API}/albums").respond(json={"id": "alb1"})
    respx.patch(f"{API}/assets").respond(json=[])
    respx.patch(url__regex=rf"{API}/albums/.*").respond(json={"id": "alb1"})

    await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    with closing(sqlite3.connect(str(catalog))) as conn:
        conn.execute(
            "INSERT INTO AgLibraryCollection(id_local, name, parent, creationId) "
            "VALUES (2, 'Portraits', NULL, 'com.adobe.ag.library.collection')"
        )
        conn.execute("UPDATE AgLibraryCollectionImage SET collection = 2")
        conn.commit()

    respx.reset()
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    mock_albums({"alb1": ["a1"]})
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.post(f"{API}/albums").respond(json={"id": "alb2"})
    respx.patch(f"{API}/assets").respond(json=[])
    respx.patch(url__regex=rf"{API}/albums/.*").respond(json={"id": "alb1"})
    removed = respx.delete(f"{API}/albums/alb1/assets").respond(json=[])

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    assert summary.albums_created == 1
    assert removed.called


@respx.mock
@pytest.mark.anyio
async def test_force_ignores_fingerprint(
    cfg: Config, client: ImmichClient, state: StateDB, catalog: Path
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.post(f"{API}/albums").respond(json={"id": "alb1"})
    respx.patch(f"{API}/assets").respond(json=[])
    respx.patch(url__regex=rf"{API}/albums/.*").respond(json={"id": "alb1"})
    respx.put(url__regex=rf"{API}/albums/.*/assets").respond(json=[])

    await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=False)

    respx.reset()
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    mock_albums({"alb1": ["a1"]})
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.patch(f"{API}/assets").respond(json=[])
    respx.patch(url__regex=rf"{API}/albums/.*").respond(json={"id": "alb1"})
    respx.put(url__regex=rf"{API}/albums/.*/assets").respond(json=[])

    await run_sync(cfg, cfg.catalogs[0], client, state, force=True)

    assert respx.calls.call_count > 0


@respx.mock
@pytest.mark.anyio
async def test_on_confirm_skips_rejected_steps(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.patch(f"{API}/assets").respond(json=[])

    confirmed: list[str] = []

    def on_confirm(name: str, msg: str) -> bool:
        confirmed.append(name)
        return name != "albums"

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, on_confirm=on_confirm)

    assert "albums" in confirmed
    album_creates = [
        c
        for c in respx.calls
        if c.request.method == "POST" and "/albums" in str(c.request.url)
    ]
    assert len(album_creates) == 0
    assert summary.albums_created == 0
    assert summary.assets_added == 0


@respx.mock
@pytest.mark.anyio
async def test_unresolved_paths_are_counted(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(json=[])
    respx.get(f"{API}/tags").respond(json=[])
    respx.get(f"{API}/albums").respond(json=[])

    summary = await run_sync(cfg, cfg.catalogs[0], client, state, dry_run=True)

    assert summary.unresolved == 1
    assert not summary.has_drift


@pytest.mark.parametrize(
    "search_status,expected",
    [
        (200, "albums: Removing 9 assets (90%) from 'Travel'"),
        (404, "albums: 404 for POST /search/metadata"),
    ],
)
@respx.mock
@pytest.mark.anyio
async def test_step_failure_is_reported(
    cfg: Config,
    client: ImmichClient,
    state: StateDB,
    search_status: int,
    expected: str,
) -> None:
    cfg.sync.album_mode = "managed"
    state.upsert_album_ownership(1, "alb1", "Travel")
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )
    respx.get(f"{API}/tags").respond(json=[])
    respx.post(f"{API}/tags").respond(json={"id": "t1", "value": "x"})
    respx.put(f"{API}/tags/t1/assets").respond(json=[])
    respx.patch(f"{API}/assets").respond(json=[])
    respx.patch(url__regex=rf"{API}/albums/.*").respond(json={})
    search = mock_albums({"alb1": ["a1", *(f"x{i}" for i in range(9))]})
    if search_status != 200:
        search.mock(return_value=httpx.Response(search_status))

    summary = await run_sync(cfg, cfg.catalogs[0], client, state)

    assert any(e.startswith(expected) for e in summary.errors)
    assert summary.favorites.favorited == 1
    assert state.get_meta("catalog_fingerprint") is None


@respx.mock
@pytest.mark.anyio
async def test_catalog_failure_is_reported(cfg: Config, client: ImmichClient) -> None:
    respx.get(f"{API}/view/folder/unique-paths").mock(
        side_effect=httpx.ConnectError("refused")
    )

    summary = await run_multi_sync(cfg, client)

    assert summary.errors == ["test.lrcat: refused"]
