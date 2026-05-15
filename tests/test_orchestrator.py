from pathlib import Path

import pytest
import respx

from lrimmich.config import Config
from lrimmich.immich import ImmichClient
from lrimmich.orchestrator import SyncSummary, run_sync
from lrimmich.state import StateDB
from tests.fixtures.catalog_factory import CatalogBuilder

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


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
        catalog=catalog,
        immich_url=IMMICH_URL,
        api_key="test-key",
    )


@respx.mock
def test_dry_run_no_mutations(
    cfg: Config, client: ImmichClient, state: StateDB
) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=["photos"])
    respx.get(f"{API}/view/folder").respond(
        json=[{"id": "a1", "originalPath": "photos/sunset.jpg"}]
    )

    summary = run_sync(cfg, client, state, dry_run=True)

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
def test_json_shape(cfg: Config, client: ImmichClient, state: StateDB) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=[])

    summary = run_sync(cfg, client, state, dry_run=True)
    d = summary.to_dict()

    assert "albums_created" in d
    assert "favorites" in d
    assert "errors" in d


@respx.mock
def test_status_stable(cfg: Config, client: ImmichClient, state: StateDB) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=[])

    s1 = run_sync(cfg, client, state, dry_run=True)
    s2 = run_sync(cfg, client, state, dry_run=True)

    assert s1.to_dict() == s2.to_dict()


@respx.mock
def test_partial_failure(cfg: Config, client: ImmichClient, state: StateDB) -> None:
    respx.get(f"{API}/view/folder/unique-paths").respond(json=[])
    cfg.sync.albums = True
    cfg.sync.favorites = True

    summary = run_sync(cfg, client, state, dry_run=True)

    assert isinstance(summary, SyncSummary)


def test_summary_no_drift() -> None:
    s = SyncSummary()
    assert not s.has_drift


def test_summary_has_drift() -> None:
    s = SyncSummary(albums_created=1)
    assert s.has_drift
