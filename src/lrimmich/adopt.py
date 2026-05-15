from dataclasses import dataclass

from lrimmich.catalog import LrCollection
from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB


@dataclass
class AdoptCandidate:
    lr_collection_id: int
    collection_name: str
    immich_album_id: str
    conflict: bool = False
    conflict_owner: int | None = None


def find_adopt_candidates(
    collections: list[LrCollection],
    client: ImmichClient,
    state: StateDB,
) -> list[AdoptCandidate]:
    albums = client.get_albums()
    name_to_album: dict[str, dict[str, str]] = {}
    for album in albums:
        name_to_album[album["albumName"]] = album

    candidates: list[AdoptCandidate] = []
    for col in collections:
        ownership = state.get_album_ownership(col.id)
        if ownership is not None:
            continue

        matched = name_to_album.get(col.full_name)
        if matched is None:
            continue

        immich_id = matched["id"]
        existing = state.get_album_by_immich_id(immich_id)

        if existing is not None:
            candidates.append(
                AdoptCandidate(
                    lr_collection_id=col.id,
                    collection_name=col.full_name,
                    immich_album_id=immich_id,
                    conflict=True,
                    conflict_owner=existing["lr_collection_id"],
                )
            )
        else:
            candidates.append(
                AdoptCandidate(
                    lr_collection_id=col.id,
                    collection_name=col.full_name,
                    immich_album_id=immich_id,
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
