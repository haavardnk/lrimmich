from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import FavoritesResult, SyncSummary
from lrimmich.utils.config import Config

FavoritesPlan = tuple[list[str], list[str]]
SNAPSHOT_KEY = "favorites_snapshot"


def plan_favorites_sync(
    flagged: set[str],
    resolved: dict[str, str],
    state: StateDB,
) -> FavoritesPlan:
    desired: set[str] = set()
    undesired: set[str] = set()
    for rp, asset_id in resolved.items():
        if rp in flagged:
            desired.add(asset_id)
        else:
            undesired.add(asset_id)
    previous = set(state.get_snapshot(SNAPSHOT_KEY) or [])
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
        previous = set(state.get_snapshot(SNAPSHOT_KEY) or [])
        state.set_snapshot(
            SNAPSHOT_KEY, sorted((previous | set(to_add)) - set(to_remove))
        )
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
        to_fav, to_unfav = plan_favorites_sync(ctx.flagged, ctx.resolved, ctx.state)
        summary.favorites = FavoritesResult(
            favorited=len(to_fav), unfavorited=len(to_unfav)
        )
        return to_fav, to_unfav

    async def apply(self, plan: FavoritesPlan, ctx: SyncContext) -> None:
        await apply_favorites_sync(plan[0], plan[1], ctx.client, ctx.state)
