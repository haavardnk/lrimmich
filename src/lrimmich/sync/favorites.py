from dataclasses import dataclass

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB


@dataclass
class FavoritesResult:
    favorited: int = 0
    unfavorited: int = 0


def _scoped_asset_ids(
    scope: str,
    collections: list[LrCollection],
    state: StateDB,
) -> dict[str, str]:
    cached = state.get_all_cached_paths()
    if scope == "all":
        return cached
    collection_paths: set[str] = set()
    for col in collections:
        collection_paths.update(col.relative_paths)
    return {rp: aid for rp, aid in cached.items() if rp in collection_paths}


def plan_favorites_sync(
    flagged: set[str],
    scope: str,
    collections: list[LrCollection],
    state: StateDB,
) -> tuple[list[str], list[str]]:
    scoped = _scoped_asset_ids(scope, collections, state)
    desired_favs: set[str] = set()
    desired_unfavs: set[str] = set()
    for rp, asset_id in scoped.items():
        if rp in flagged:
            desired_favs.add(asset_id)
        else:
            desired_unfavs.add(asset_id)
    previous = state.get_synced_favorites()
    to_favorite = sorted(desired_favs - previous)
    to_unfavorite = sorted(desired_unfavs & previous)
    return to_favorite, to_unfavorite


def apply_favorites_sync(
    to_favorite: list[str],
    to_unfavorite: list[str],
    client: ImmichClient,
    state: StateDB,
) -> FavoritesResult:
    if to_favorite:
        client.bulk_update_assets(to_favorite, isFavorite=True)
    if to_unfavorite:
        client.bulk_update_assets(to_unfavorite, isFavorite=False)
    result = FavoritesResult(
        favorited=len(to_favorite),
        unfavorited=len(to_unfavorite),
    )
    if to_favorite or to_unfavorite:
        previous = state.get_synced_favorites()
        updated = (previous | set(to_favorite)) - set(to_unfavorite)
        state.replace_synced_favorites(updated)
        state.append_audit_log(
            "sync_favorites",
            "favorites",
            payload={
                "favorited": result.favorited,
                "unfavorited": result.unfavorited,
            },
        )
    return result
