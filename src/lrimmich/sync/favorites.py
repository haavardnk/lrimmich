from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import FavoritesResult, SyncSummary
from lrimmich.utils.config import Config

FavoritesPlan = tuple[list[str], list[str]]


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
    desired: set[str] = set()
    undesired: set[str] = set()
    for rp, asset_id in scoped.items():
        if rp in flagged:
            desired.add(asset_id)
        else:
            undesired.add(asset_id)
    previous = state.get_synced_favorites()
    return sorted(desired - previous), sorted(undesired & previous)


async def apply_favorites_sync(
    to_add: list[str],
    to_remove: list[str],
    client: ImmichClient,
    state: StateDB,
) -> FavoritesResult:
    if to_add:
        await client.bulk_update_assets(to_add, isFavorite=True)
    if to_remove:
        await client.bulk_update_assets(to_remove, isFavorite=False)
    if to_add or to_remove:
        updated = (state.get_synced_favorites() | set(to_add)) - set(to_remove)
        state.replace_synced_favorites(updated)
        state.append_audit_log(
            "sync_favorites",
            "favorites",
            payload={"favorited": len(to_add), "unfavorited": len(to_remove)},
        )
    return FavoritesResult(favorited=len(to_add), unfavorited=len(to_remove))


class Step:
    name = "favorites"
    status_msg = "Syncing favorites..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.favorites

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> FavoritesPlan:
        to_fav, to_unfav = plan_favorites_sync(
            ctx.get_flagged(), ctx.cfg.sync.scope, ctx.collections, ctx.state
        )
        summary.favorites = FavoritesResult(
            favorited=len(to_fav), unfavorited=len(to_unfav)
        )
        return to_fav, to_unfav

    async def apply(self, plan: FavoritesPlan, ctx: SyncContext) -> None:
        await apply_favorites_sync(plan[0], plan[1], ctx.client, ctx.state)
