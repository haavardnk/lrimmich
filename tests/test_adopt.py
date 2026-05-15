from pathlib import Path

import httpx
import pytest
import respx

from lrimmich.adopt import AdoptCandidate, apply_adopt, find_adopt_candidates
from lrimmich.catalog import LrCollection
from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


@pytest.fixture()
def state(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


@pytest.fixture()
def client() -> ImmichClient:
    return ImmichClient(IMMICH_URL, "test-key")


def _col(
    id: int = 1,
    name: str = "Album",
    full_name: str = "Album",
) -> LrCollection:
    return LrCollection(id=id, name=name, full_name=full_name, relative_paths=[])


@respx.mock
def test_match_found(state: StateDB, client: ImmichClient) -> None:
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": "Travel"}],
        )
    )
    col = _col(id=10, full_name="Travel")

    candidates = find_adopt_candidates([col], client, state)

    assert len(candidates) == 1
    assert candidates[0].immich_album_id == "imm-1"
    assert not candidates[0].conflict


@respx.mock
def test_no_match(state: StateDB, client: ImmichClient) -> None:
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": "Other"}],
        )
    )
    col = _col(id=10, full_name="Travel")

    candidates = find_adopt_candidates([col], client, state)

    assert len(candidates) == 0


@respx.mock
def test_already_owned_skipped(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "imm-1", "Travel")
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": "Travel"}],
        )
    )
    col = _col(id=10, full_name="Travel")

    candidates = find_adopt_candidates([col], client, state)

    assert len(candidates) == 0


@respx.mock
def test_conflict_state_owner(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(99, "imm-1", "OldOwner")
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": "Travel"}],
        )
    )
    col = _col(id=10, full_name="Travel")

    candidates = find_adopt_candidates([col], client, state)

    assert len(candidates) == 1
    assert candidates[0].conflict
    assert candidates[0].conflict_owner == 99


def test_apply_adopt(state: StateDB) -> None:
    candidates = [
        AdoptCandidate(
            lr_collection_id=10,
            collection_name="Travel",
            immich_album_id="imm-1",
        ),
    ]

    adopted = apply_adopt(candidates, state)

    assert adopted == 1
    assert state.get_album_ownership(10) is not None
    assert len(state.get_audit_log()) == 1


def test_apply_skips_conflicts(state: StateDB) -> None:
    candidates = [
        AdoptCandidate(
            lr_collection_id=10,
            collection_name="Travel",
            immich_album_id="imm-1",
            conflict=True,
            conflict_owner=99,
        ),
    ]

    adopted = apply_adopt(candidates, state)

    assert adopted == 0
    assert state.get_album_ownership(10) is None
