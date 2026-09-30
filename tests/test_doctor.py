from pathlib import Path

import httpx
import pytest
import respx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.utils.config import Config
from lrimmich.utils.doctor import (
    check_api_permissions,
    check_catalog,
    check_immich,
    check_path_mapping,
    check_state_db,
    check_wal_lock,
    run_doctor,
)
from tests.fixtures.catalog_factory import CatalogBuilder

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def catalog(tmp_path: Path) -> Path:
    builder = CatalogBuilder(tmp_path / "test.lrcat")
    builder.add_collection(1, "Test")
    builder.add_image(1, "img.jpg", "photos/")
    builder.add_collection_image(1, 1)
    return builder.build()


def test_check_catalog_pass(catalog: Path) -> None:
    result = check_catalog(catalog)
    assert result.ok


def test_check_catalog_not_found(tmp_path: Path) -> None:
    result = check_catalog(tmp_path / "missing.lrcat")
    assert not result.ok
    assert "Not found" in result.message


def test_check_wal_no_wal(catalog: Path) -> None:
    result = check_wal_lock(catalog)
    assert result.ok
    assert "No WAL" in result.message


def test_check_wal_unlocked(catalog: Path) -> None:
    wal = catalog.parent / (catalog.name + "-wal")
    wal.write_bytes(b"\x00" * 32)
    result = check_wal_lock(catalog)
    assert result.ok


@respx.mock
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("version", "version_ok"),
    [("v3.0.0", True), ("2.9.1", False)],
)
async def test_check_immich_reports_version(
    client: ImmichClient, version: str, version_ok: bool
) -> None:
    respx.get(f"{API}/server/about").mock(
        return_value=httpx.Response(200, json={"version": version})
    )
    reachable, detected = await check_immich(client)
    assert reachable.ok
    assert detected.ok is version_ok


@respx.mock
@pytest.mark.anyio
async def test_check_immich_fail(client: ImmichClient) -> None:
    respx.get(f"{API}/server/about").mock(return_value=httpx.Response(500))
    results = await check_immich(client)
    assert len(results) == 1
    assert not results[0].ok


@respx.mock
@pytest.mark.anyio
async def test_check_api_permissions_pass(client: ImmichClient) -> None:
    respx.get(f"{API}/albums").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{API}/tags").mock(return_value=httpx.Response(200, json=[]))
    result = await check_api_permissions(client)
    assert result.ok


@respx.mock
@pytest.mark.anyio
async def test_check_api_permissions_fail(client: ImmichClient) -> None:
    respx.get(f"{API}/albums").mock(return_value=httpx.Response(401))
    result = await check_api_permissions(client)
    assert not result.ok


@respx.mock
@pytest.mark.anyio
async def test_check_path_mapping_pass(catalog: Path, client: ImmichClient) -> None:
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "a1", "originalPath": "/ext/photos/img.jpg"}],
        )
    )
    result = await check_path_mapping(["/ext/"], catalog, client)
    assert result.ok


@respx.mock
@pytest.mark.anyio
async def test_check_path_mapping_no_assets(
    catalog: Path, client: ImmichClient
) -> None:
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(200, json=[]),
    )
    result = await check_path_mapping(["/ext/"], catalog, client)
    assert not result.ok
    assert "/ext/" in result.message


@respx.mock
@pytest.mark.anyio
async def test_check_path_mapping_empty(catalog: Path) -> None:
    client = ImmichClient(IMMICH_URL, "test-key")
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(200, json=[]),
    )
    result = await check_path_mapping([""], catalog, client)
    assert not result.ok


def test_check_state_db_pass(state: StateDB) -> None:
    result = check_state_db(state)
    assert result.ok


@respx.mock
@pytest.mark.anyio
async def test_run_doctor_all_pass(
    catalog: Path, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/server/about").mock(
        return_value=httpx.Response(200, json={"version": "v3.0.0"})
    )
    respx.get(f"{API}/albums").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{API}/tags").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "a1", "originalPath": "/ext/photos/img.jpg"}],
        )
    )
    cfg = Config(
        catalogs=[{"catalog": catalog}],
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_paths": ["/ext/"]},
    )
    report = await run_doctor(cfg, client)
    assert report.all_ok
    assert len(report.checks) >= 5


@respx.mock
@pytest.mark.anyio
async def test_run_doctor_partial_fail(
    tmp_path: Path, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/server/about").mock(return_value=httpx.Response(500))
    respx.get(f"{API}/albums").mock(return_value=httpx.Response(401))
    cfg = Config(
        catalogs=[{"catalog": tmp_path / "missing.lrcat"}],
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_paths": ["/ext/"]},
    )
    report = await run_doctor(cfg, client)
    assert not report.all_ok


@respx.mock
@pytest.mark.anyio
async def test_check_path_mapping_with_strip(
    tmp_path: Path, client: ImmichClient
) -> None:
    builder = CatalogBuilder(tmp_path / "test.lrcat")
    builder.add_image(1, "img.jpg", "Root/photos/")
    catalog = builder.build()
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "a1", "originalPath": "/ext/photos/img.jpg"}],
        )
    )
    result = await check_path_mapping(["/ext/"], catalog, client, strip="Root/")
    assert result.ok
