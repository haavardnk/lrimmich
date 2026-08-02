import json

from lrimmich.clients.catalog import read_captions
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import CaptionsResult, SyncSummary
from lrimmich.utils.config import Config

CaptionsPlan = tuple[dict[str, str], list[str]]


def plan_captions_sync(
    captions: dict[str, str],
    resolved: dict[str, str],
    state: StateDB,
) -> tuple[dict[str, str], list[str]]:
    previous = state.get_meta("captions_snapshot")
    prev_assignments: dict[str, str] = json.loads(previous) if previous else {}

    desired: dict[str, str] = {
        resolved[rp]: cap for rp, cap in captions.items() if rp in resolved
    }

    to_set = {
        aid: cap for aid, cap in desired.items() if prev_assignments.get(aid) != cap
    }
    to_clear = [aid for aid in prev_assignments if aid not in desired]
    return to_set, to_clear


async def apply_captions_sync(
    to_set: dict[str, str],
    to_clear: list[str],
    client: ImmichClient,
    state: StateDB,
) -> CaptionsResult:
    by_caption: dict[str, list[str]] = {}
    for asset_id, caption in to_set.items():
        by_caption.setdefault(caption, []).append(asset_id)
    for caption, asset_ids in by_caption.items():
        await client.bulk_update_assets(sorted(asset_ids), description=caption)
    if to_clear:
        await client.bulk_update_assets(sorted(to_clear), description="")
    if to_set or to_clear:
        snapshot = dict(json.loads(state.get_meta("captions_snapshot") or "{}"))
        snapshot.update(to_set)
        for aid in to_clear:
            snapshot.pop(aid, None)
        state.set_meta("captions_snapshot", json.dumps(snapshot))
        state.append_audit_log(
            "sync_captions",
            "captions",
            payload={"set": len(to_set), "cleared": len(to_clear)},
        )
    return CaptionsResult(set=len(to_set), cleared=len(to_clear))


class Step:
    name = "captions"
    status_msg = "Syncing captions..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.captions

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> CaptionsPlan:
        captions = read_captions(ctx.catalog.catalog)
        to_set, to_clear = plan_captions_sync(captions, ctx.resolved, ctx.state)
        summary.captions = CaptionsResult(set=len(to_set), cleared=len(to_clear))
        return to_set, to_clear

    async def apply(self, plan: CaptionsPlan, ctx: SyncContext) -> None:
        await apply_captions_sync(plan[0], plan[1], ctx.client, ctx.state)
