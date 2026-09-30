from dataclasses import dataclass

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import RejectsResult, SyncSummary
from lrimmich.sync.tags import TagPlan, apply_tags, plan_tags
from lrimmich.utils.config import Config

ArchivePlan = tuple[list[str], list[str]]
SNAPSHOT_KEY = "rejects_snapshot"
TAG_SNAPSHOT_KEY = "reject_tag_snapshot"


@dataclass
class RejectsPlan:
    archive: list[str]
    unarchive: list[str]
    tags: TagPlan


def plan_rejects_sync(
    rejected: set[str],
    resolved: dict[str, str],
    state: StateDB,
) -> ArchivePlan:
    desired: set[str] = set()
    undesired: set[str] = set()
    for rp, asset_id in resolved.items():
        if rp in rejected:
            desired.add(asset_id)
        else:
            undesired.add(asset_id)
    previous = set(state.get_snapshot(SNAPSHOT_KEY) or [])
    return sorted(desired - previous), sorted(undesired & previous)


async def apply_rejects_sync(
    to_add: list[str],
    to_remove: list[str],
    client: ImmichClient,
    state: StateDB,
) -> RejectsResult:
    if to_add:
        await client.bulk_update_assets(to_add, visibility="archive")
    if to_remove:
        await client.bulk_update_assets(to_remove, visibility="timeline")
    if to_add or to_remove:
        previous = set(state.get_snapshot(SNAPSHOT_KEY) or [])
        state.set_snapshot(
            SNAPSHOT_KEY, sorted((previous | set(to_add)) - set(to_remove))
        )
        state.append_audit_log(
            "sync_rejects",
            "rejects",
            payload={"archived": len(to_add), "unarchived": len(to_remove)},
        )
    return RejectsResult(archived=len(to_add), unarchived=len(to_remove))


class Step:
    name = "rejects"
    status_msg = "Syncing rejects..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.rejects

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> RejectsPlan:
        tag = ctx.cfg.sync.reject_mode == "tag"
        archived = set() if tag else ctx.rejected
        to_arch, to_unarch = plan_rejects_sync(archived, ctx.resolved, ctx.state)
        desired = (
            {
                ctx.resolved[rp]: [ctx.cfg.sync.reject_tag]
                for rp in ctx.rejected
                if rp in ctx.resolved
            }
            if tag
            else {}
        )
        tags = await plan_tags(ctx, desired, TAG_SNAPSHOT_KEY)
        summary.rejects = RejectsResult(
            archived=len(to_arch),
            unarchived=len(to_unarch),
            tagged=tags.result.tagged,
            untagged=tags.result.untagged,
        )
        return RejectsPlan(to_arch, to_unarch, tags)

    async def apply(self, plan: RejectsPlan, ctx: SyncContext) -> None:
        await apply_rejects_sync(plan.archive, plan.unarchive, ctx.client, ctx.state)
        await apply_tags(ctx, plan.tags, TAG_SNAPSHOT_KEY, "sync_reject_tags")
