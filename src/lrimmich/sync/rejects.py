from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import RejectsResult, SyncSummary
from lrimmich.utils.config import Config

RejectsPlan = tuple[list[str], list[str]]


def plan_rejects_sync(
    rejected: set[str],
    resolved: dict[str, str],
    state: StateDB,
) -> tuple[list[str], list[str]]:
    desired: set[str] = set()
    undesired: set[str] = set()
    for rp, asset_id in resolved.items():
        if rp in rejected:
            desired.add(asset_id)
        else:
            undesired.add(asset_id)
    previous = state.get_synced_rejects()
    return sorted(desired - previous), sorted(undesired & previous)


async def apply_rejects_sync(
    to_add: list[str],
    to_remove: list[str],
    client: ImmichClient,
    state: StateDB,
) -> RejectsResult:
    if to_add:
        await client.bulk_update_assets(to_add, isArchived=True)
    if to_remove:
        await client.bulk_update_assets(to_remove, isArchived=False)
    if to_add or to_remove:
        updated = (state.get_synced_rejects() | set(to_add)) - set(to_remove)
        state.replace_synced_rejects(updated)
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
        to_arch, to_unarch = plan_rejects_sync(
            ctx.get_rejected(), ctx.resolved, ctx.state
        )
        summary.rejects = RejectsResult(
            archived=len(to_arch), unarchived=len(to_unarch)
        )
        return to_arch, to_unarch

    async def apply(self, plan: RejectsPlan, ctx: SyncContext) -> None:
        await apply_rejects_sync(plan[0], plan[1], ctx.client, ctx.state)
