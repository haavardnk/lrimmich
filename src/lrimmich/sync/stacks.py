from dataclasses import dataclass
from typing import Any

from lrimmich.clients.catalog import LrStack, read_stacks
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import StacksResult, SyncSummary
from lrimmich.utils.config import Config

SNAPSHOT_KEY = "stacks_snapshot"


@dataclass
class StackAction:
    kind: str
    lr_stack_id: str
    asset_ids: list[str]
    immich_stack_id: str | None = None


@dataclass
class StackPlan:
    actions: list[StackAction]
    owned: dict[str, str]

    @property
    def result(self) -> StacksResult:
        kinds = [a.kind for a in self.actions]
        return StacksResult(
            created=kinds.count("create"),
            updated=kinds.count("update"),
            deleted=kinds.count("delete"),
        )


def _matches(stack: dict[str, Any], asset_ids: list[str]) -> bool:
    return stack["primaryAssetId"] == asset_ids[0] and {
        a["id"] for a in stack["assets"]
    } == set(asset_ids)


async def plan_stack_sync(
    lr_stacks: list[LrStack],
    resolved: dict[str, str],
    state: StateDB,
    client: ImmichClient,
) -> StackPlan:
    existing = {s["id"]: s for s in await client.get_stacks()}
    previous: dict[str, str] = state.get_snapshot(SNAPSHOT_KEY) or {}
    live = {k: existing[v] for k, v in previous.items() if v in existing}
    grouped = {
        str(s.stack_id): list(
            dict.fromkeys(resolved[p] for p in s.paths if p in resolved)
        )
        for s in lr_stacks
    }
    desired = {k: ids for k, ids in grouped.items() if len(ids) >= 2}
    changed = [
        StackAction("update", k, ids, live[k]["id"])
        if k in live
        else StackAction("create", k, ids)
        for k, ids in desired.items()
        if k not in live or not _matches(live[k], ids)
    ]
    removed = [
        StackAction("delete", k, [], stack["id"])
        for k, stack in live.items()
        if k not in desired
    ]
    return StackPlan(changed + removed, {k: s["id"] for k, s in live.items()})


async def apply_stack_sync(
    plan: StackPlan, client: ImmichClient, state: StateDB
) -> None:
    owned = dict(plan.owned)
    try:
        for action in plan.actions:
            if action.immich_stack_id:
                await client.delete_stack(action.immich_stack_id)
                owned.pop(action.lr_stack_id)
            if action.kind == "delete":
                state.append_audit_log("delete_stack", "stack", action.immich_stack_id)
                continue
            created = await client.create_stack(action.asset_ids)
            owned[action.lr_stack_id] = created["id"]
            state.append_audit_log(
                f"{action.kind}_stack",
                "stack",
                created["id"],
                {"assets": len(action.asset_ids)},
            )
    finally:
        state.set_snapshot(SNAPSHOT_KEY, owned)


class Step:
    name = "stacks"
    status_msg = "Syncing stacks..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.stacks

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> StackPlan:
        plan = await plan_stack_sync(
            read_stacks(ctx.catalog.catalog), ctx.resolved, ctx.state, ctx.client
        )
        summary.stacks = plan.result
        return plan

    async def apply(self, plan: StackPlan, ctx: SyncContext) -> None:
        await apply_stack_sync(plan, ctx.client, ctx.state)
