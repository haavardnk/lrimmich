from lrimmich.clients.catalog import read_collection_covers
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import CoversResult, SyncSummary
from lrimmich.utils.config import Config

CoversPlan = tuple[dict[str, str], list[str]]


def plan_covers_sync(
    cover_paths: dict[int, str],
    resolved: dict[str, str],
    state: StateDB,
) -> tuple[dict[str, str], list[str]]:
    desired: dict[str, str] = {}
    for lr_id, rel_path in cover_paths.items():
        if rel_path not in resolved:
            continue
        ownership = state.get_album_ownership(lr_id)
        if ownership is None:
            continue
        desired[ownership["immich_album_id"]] = resolved[rel_path]
    previous = state.get_synced_covers()
    to_set = {
        aid: asset for aid, asset in desired.items() if previous.get(aid) != asset
    }
    to_clear = [aid for aid in previous if aid not in desired]
    return to_set, to_clear


def apply_covers_sync(
    to_set: dict[str, str],
    to_clear: list[str],
    client: ImmichClient,
    state: StateDB,
) -> CoversResult:
    for album_id, asset_id in sorted(to_set.items()):
        client.update_album(album_id, albumThumbnailAssetId=asset_id)
    for album_id in sorted(to_clear):
        client.update_album(album_id, albumThumbnailAssetId=None)
    if to_set or to_clear:
        snapshot = dict(state.get_synced_covers())
        snapshot.update(to_set)
        for aid in to_clear:
            snapshot.pop(aid, None)
        state.replace_synced_covers(snapshot)
        state.append_audit_log(
            "sync_covers",
            "albums",
            payload={"set": len(to_set), "cleared": len(to_clear)},
        )
    return CoversResult(set=len(to_set), cleared=len(to_clear))


class Step:
    name = "covers"
    status_msg = "Syncing album covers..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.albums

    def plan(self, ctx: SyncContext, summary: SyncSummary) -> CoversPlan:
        cover_paths = read_collection_covers(ctx.cfg.lightroom.catalog)
        to_set, to_clear = plan_covers_sync(cover_paths, ctx.resolved, ctx.state)
        summary.covers = CoversResult(set=len(to_set), cleared=len(to_clear))
        return to_set, to_clear

    def apply(self, plan: CoversPlan, ctx: SyncContext) -> None:
        apply_covers_sync(plan[0], plan[1], ctx.client, ctx.state)
