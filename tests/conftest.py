from pathlib import Path

import pytest

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB

IMMICH_URL = "http://immich.test"


@pytest.fixture()
def base_url() -> str:
    return IMMICH_URL


@pytest.fixture()
def api_url() -> str:
    return IMMICH_URL + "/api"


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")
