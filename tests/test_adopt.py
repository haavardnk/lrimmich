import httpx
import pytest
import respx

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.utils.adopt import AdoptCandidate, apply_adopt, find_adopt_candidates

IMMICH_URL = "http://immich.test"
API = IMMICH_URL + "/api"


def _col(
    id: int = 1,
    name: str = "Album",
    full_name: str = "Album",
) -> LrCollection:
    return LrCollection(id=id, name=name, full_name=full_name, relative_paths=[])


@respx.mock
@pytest.mark.anyio
@pytest.mark.parametrize(
    "fmt,album_name,matched",
    [
        ("{path}", "Trips/Travel", True),
        ("{name}", "Travel", True),
        ("{name}", "Trips/Travel", False),
    ],
)
async def test_match_uses_album_name_format(
    state: StateDB, client: ImmichClient, fmt: str, album_name: str, matched: bool
) -> None:
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": album_name}],
        )
    )
    col = _col(id=10, name="Travel", full_name="Trips/Travel")

    candidates = await find_adopt_candidates([col], client, state, fmt)

    assert [(c.immich_album_id, c.collection_name) for c in candidates] == (
        [("imm-1", album_name)] if matched else []
    )
    assert not any(c.conflict for c in candidates)


@respx.mock
@pytest.mark.anyio
@pytest.mark.parametrize(
    "album_ids,collection_ids,expected",
    [
        (["imm-1"], [10, 11], [(10, False), (11, True)]),
        (["imm-1", "imm-2"], [10], [(10, True)]),
    ],
)
async def test_ambiguous_names_are_conflicts(
    state: StateDB,
    client: ImmichClient,
    album_ids: list[str],
    collection_ids: list[int],
    expected: list[tuple[int, bool]],
) -> None:
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200, json=[{"id": aid, "albumName": "Travel"} for aid in album_ids]
        )
    )
    cols = [
        _col(id=cid, name="Travel", full_name=f"{cid}/Travel") for cid in collection_ids
    ]

    candidates = await find_adopt_candidates(cols, client, state, "{name}")

    assert [(c.lr_collection_id, c.conflict) for c in candidates] == expected


@respx.mock
@pytest.mark.anyio
async def test_no_match(state: StateDB, client: ImmichClient) -> None:
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": "Other"}],
        )
    )
    col = _col(id=10, full_name="Travel")

    candidates = await find_adopt_candidates([col], client, state)

    assert len(candidates) == 0


@respx.mock
@pytest.mark.anyio
async def test_already_owned_skipped(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(10, "imm-1", "Travel")
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": "Travel"}],
        )
    )
    col = _col(id=10, full_name="Travel")

    candidates = await find_adopt_candidates([col], client, state)

    assert len(candidates) == 0


@respx.mock
@pytest.mark.anyio
async def test_conflict_state_owner(state: StateDB, client: ImmichClient) -> None:
    state.upsert_album_ownership(99, "imm-1", "OldOwner")
    respx.get(f"{API}/albums").mock(
        return_value=httpx.Response(
            200,
            json=[{"id": "imm-1", "albumName": "Travel"}],
        )
    )
    col = _col(id=10, full_name="Travel")

    candidates = await find_adopt_candidates([col], client, state)

    assert len(candidates) == 1
    assert candidates[0].conflict


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
        ),
    ]

    adopted = apply_adopt(candidates, state)

    assert adopted == 0
    assert state.get_album_ownership(10) is None
