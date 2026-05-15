from dataclasses import dataclass

from lrimmich.catalog import LrCollection
from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB


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
    to_favorite: list[str] = []
    to_unfavorite: list[str] = []
    for rp, asset_id in scoped.items():
        if rp in flagged:
            to_favorite.append(asset_id)
        else:
            to_unfavorite.append(asset_id)
    return sorted(to_favorite), sorted(to_unfavorite)


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
        state.append_audit_log(
            "sync_favorites",
            "favorites",
            payload={
                "favorited": result.favorited,
                "unfavorited": result.unfavorited,
            },
        )
    return result
