from dataclasses import dataclass

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.albums import format_album_name


@dataclass
class AdoptCandidate:
    lr_collection_id: int
    collection_name: str
    immich_album_id: str
    conflict: bool = False
    conflict_owner: int | None = None


async def find_adopt_candidates(
    collections: list[LrCollection],
    client: ImmichClient,
    state: StateDB,
    album_name_format: str = "{path}",
) -> list[AdoptCandidate]:
    albums = await client.get_albums()
    name_to_albums: dict[str, list[dict[str, str]]] = {}
    for album in albums:
        name_to_albums.setdefault(album["albumName"], []).append(album)

    claimed: dict[str, int] = {}
    candidates: list[AdoptCandidate] = []
    for col in collections:
        ownership = state.get_album_ownership(col.id)
        if ownership is not None:
            continue

        album_name = format_album_name(col, album_name_format)
        matches = name_to_albums.get(album_name, [])
        if not matches:
            continue

        immich_id = matches[0]["id"]
        existing = state.get_album_by_immich_id(immich_id)
        owner = existing["lr_collection_id"] if existing else claimed.get(immich_id)
        conflict = len(matches) > 1 or owner is not None
        if not conflict:
            claimed[immich_id] = col.id
        candidates.append(
            AdoptCandidate(
                lr_collection_id=col.id,
                collection_name=album_name,
                immich_album_id=immich_id,
                conflict=conflict,
                conflict_owner=owner,
            )
        )

    return candidates


def apply_adopt(
    candidates: list[AdoptCandidate],
    state: StateDB,
) -> int:
    adopted = 0
    for c in candidates:
        if c.conflict:
            continue
        state.upsert_album_ownership(
            c.lr_collection_id, c.immich_album_id, c.collection_name
        )
        state.append_audit_log(
            "adopt_album",
            "album",
            c.immich_album_id,
            {"lr_collection_id": c.lr_collection_id, "name": c.collection_name},
        )
        adopted += 1
    return adopted
