from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.albums import album_paths, resolve_album_rule
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import CoversResult, SyncSummary
from lrimmich.utils.config import Config

CoversPlan = tuple[dict[str, str], list[str]]
SNAPSHOT_KEY = "covers_snapshot"


def pick_cover_candidates(
    collections: list[LrCollection],
    cfg: Config,
    resolved: dict[str, str],
    flagged: set[str],
    rejected: set[str],
    rated: dict[str, int],
) -> dict[int, list[str]]:
    candidates: dict[int, list[str]] = {}
    for collection in collections:
        rule = resolve_album_rule(
            collection,
            cfg.sync.album_filter,
            cfg.sync.album_min_rating,
            cfg.album_rules,
        )
        scored = {
            p: (rated.get(p, 0), 1 if p in flagged else -1 if p in rejected else 0)
            for p in album_paths(collection, rule, flagged, rejected, rated)
            if p in resolved
        }
        best = max(scored.values(), default=(0, 0))
        if best[0] > 0 or best[1] > 0:
            candidates[collection.id] = [p for p, s in scored.items() if s == best]
    return candidates


def plan_covers_sync(
    cover_candidates: dict[int, list[str]],
    resolved: dict[str, str],
    state: StateDB,
) -> CoversPlan:
    previous: dict[str, str] = state.get_snapshot(SNAPSHOT_KEY) or {}
    desired: dict[str, str] = {}
    for lr_id, paths in cover_candidates.items():
        asset_ids = [resolved[p] for p in paths if p in resolved]
        ownership = state.get_album_ownership(lr_id)
        if not asset_ids or ownership is None:
            continue
        album_id = ownership["immich_album_id"]
        current = previous.get(album_id, "")
        desired[album_id] = current if current in asset_ids else asset_ids[0]
    to_set = {
        aid: asset for aid, asset in desired.items() if previous.get(aid) != asset
    }
    stale = [aid for aid in previous if aid not in desired]
    return to_set, stale


async def apply_covers_sync(
    to_set: dict[str, str],
    stale: list[str],
    client: ImmichClient,
    state: StateDB,
) -> CoversResult:
    for album_id, asset_id in sorted(to_set.items()):
        await client.update_album(album_id, albumThumbnailAssetId=asset_id)
    if to_set or stale:
        snapshot: dict[str, str] = state.get_snapshot(SNAPSHOT_KEY) or {}
        snapshot.update(to_set)
        for aid in stale:
            snapshot.pop(aid, None)
        state.set_snapshot(SNAPSHOT_KEY, snapshot)
        state.append_audit_log(
            "sync_covers",
            "albums",
            payload={"set": len(to_set), "forgotten": len(stale)},
        )
    return CoversResult(set=len(to_set))


class Step:
    name = "covers"
    status_msg = "Syncing album covers..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.albums

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> CoversPlan:
        candidates = pick_cover_candidates(
            ctx.collections,
            ctx.cfg,
            ctx.resolved,
            ctx.flagged,
            ctx.rejected,
            ctx.rated,
        )
        to_set, stale = plan_covers_sync(candidates, ctx.resolved, ctx.state)
        summary.covers = CoversResult(set=len(to_set))
        return to_set, stale

    async def apply(self, plan: CoversPlan, ctx: SyncContext) -> None:
        await apply_covers_sync(plan[0], plan[1], ctx.client, ctx.state)
