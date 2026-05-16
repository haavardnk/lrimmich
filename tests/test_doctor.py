from pathlib import Path

import httpx
import pytest
import respx

from lrimmich.config import Config
from lrimmich.doctor import (
    check_api_permissions,
    check_catalog,
    check_immich_reachable,
    check_path_mapping,
    check_state_db,
    check_wal_lock,
    run_doctor,
)
from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB
from tests.fixtures.catalog_factory import CatalogBuilder

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


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
def test_check_immich_reachable_pass(client: ImmichClient) -> None:
    respx.get(f"{API}/server/about").mock(
        return_value=httpx.Response(200, json={"version": "1.0"})
    )
    result = check_immich_reachable(client)
    assert result.ok


@respx.mock
def test_check_immich_reachable_fail(client: ImmichClient) -> None:
    respx.get(f"{API}/server/about").mock(return_value=httpx.Response(500))
    result = check_immich_reachable(client)
    assert not result.ok


@respx.mock
def test_check_api_permissions_pass(client: ImmichClient) -> None:
    respx.get(f"{API}/albums").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{API}/tags").mock(return_value=httpx.Response(200, json=[]))
    result = check_api_permissions(client)
    assert result.ok


@respx.mock
def test_check_api_permissions_fail(client: ImmichClient) -> None:
    respx.get(f"{API}/albums").mock(return_value=httpx.Response(401))
    result = check_api_permissions(client)
    assert not result.ok


@respx.mock
def test_check_path_mapping_pass(catalog: Path, client: ImmichClient) -> None:
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "a1", "originalPath": "/ext/photos/img.jpg"}],
        )
    )
    result = check_path_mapping("/ext/", catalog, client)
    assert result.ok


@respx.mock
def test_check_path_mapping_no_assets(catalog: Path, client: ImmichClient) -> None:
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(200, json=[]),
    )
    result = check_path_mapping("/ext/", catalog, client)
    assert not result.ok


@respx.mock
def test_check_path_mapping_empty(catalog: Path) -> None:
    client = ImmichClient(IMMICH_URL, "test-key")
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(200, json=[]),
    )
    result = check_path_mapping("", catalog, client)
    assert not result.ok


def test_check_state_db_pass(state: StateDB) -> None:
    result = check_state_db(state)
    assert result.ok


@respx.mock
def test_run_doctor_all_pass(
    catalog: Path, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/server/about").mock(
        return_value=httpx.Response(200, json={"version": "1.0"})
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
        lightroom={"catalog": catalog},
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_path": "/ext/"},
    )
    report = run_doctor(cfg, client, state)
    assert report.all_ok
    assert len(report.checks) == 6


@respx.mock
def test_run_doctor_partial_fail(
    tmp_path: Path, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/server/about").mock(return_value=httpx.Response(500))
    respx.get(f"{API}/albums").mock(return_value=httpx.Response(401))
    cfg = Config(
        lightroom={"catalog": tmp_path / "missing.lrcat"},
        immich={"url": IMMICH_URL, "api_key": "test-key", "library_path": "/ext/"},
    )
    report = run_doctor(cfg, client, state)
    assert not report.all_ok
    failed = [c.name for c in report.checks if not c.ok]
    assert "catalog" in failed
    assert "immich" in failed


@respx.mock
def test_check_path_mapping_with_strip(tmp_path: Path, client: ImmichClient) -> None:
    builder = CatalogBuilder(tmp_path / "test.lrcat")
    builder.add_image(1, "img.jpg", "Root/photos/")
    catalog = builder.build()
    respx.get(f"{API}/view/folder").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "a1", "originalPath": "/ext/photos/img.jpg"}],
        )
    )
    result = check_path_mapping("/ext/", catalog, client, strip="Root/")
    assert result.ok
