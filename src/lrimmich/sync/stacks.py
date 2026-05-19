from dataclasses import dataclass

import structlog

from lrimmich.clients.catalog import LrStack, read_stacks
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import StacksResult, SyncSummary
from lrimmich.utils.config import Config

logger = structlog.get_logger()


@dataclass
class StackAction:
    kind: str
    lr_stack_id: int
    asset_ids: list[str]
    immich_stack_id: str = ""
    primary_asset_id: str = ""


StackPlan = list[StackAction]


async def plan_stack_sync(
    lr_stacks: list[LrStack],
    resolved: dict[str, str],
    state: StateDB,
    client: ImmichClient,
) -> StackPlan:
    existing = await client.get_stacks()
    primary_to_stack: dict[str, dict] = {s["primaryAssetId"]: s for s in existing}

    actions: list[StackAction] = []
    seen_primaries: set[str] = set()

    for lr_stack in lr_stacks:
        asset_ids = [resolved[p] for p in lr_stack.paths if p in resolved]
        if len(asset_ids) < 2:
            continue

        primary_id = asset_ids[0]
        seen_primaries.add(primary_id)

        owned_stack_id = state.get_meta(f"stack:{lr_stack.stack_id}")
        immich_stack = primary_to_stack.get(primary_id)

        if immich_stack and owned_stack_id == immich_stack["id"]:
            current_ids = {a["id"] for a in immich_stack.get("assets", [])}
            if current_ids == set(asset_ids):
                continue
            actions.append(
                StackAction(
                    kind="update",
                    lr_stack_id=lr_stack.stack_id,
                    asset_ids=asset_ids,
                    immich_stack_id=immich_stack["id"],
                    primary_asset_id=primary_id,
                )
            )
        elif owned_stack_id:
            actions.append(
                StackAction(
                    kind="delete",
                    lr_stack_id=lr_stack.stack_id,
                    asset_ids=[],
                    immich_stack_id=owned_stack_id,
                )
            )
            actions.append(
                StackAction(
                    kind="create",
                    lr_stack_id=lr_stack.stack_id,
                    asset_ids=asset_ids,
                    primary_asset_id=primary_id,
                )
            )
        else:
            actions.append(
                StackAction(
                    kind="create",
                    lr_stack_id=lr_stack.stack_id,
                    asset_ids=asset_ids,
                    primary_asset_id=primary_id,
                )
            )

    owned_stacks = state.get_meta_prefix("stack:")
    lr_ids = {s.stack_id for s in lr_stacks}
    for key, immich_stack_id in owned_stacks.items():
        lr_id_str = key.removeprefix("stack:")
        if not lr_id_str.isdigit():
            continue
        lr_id = int(lr_id_str)
        if lr_id not in lr_ids:
            actions.append(
                StackAction(
                    kind="delete",
                    lr_stack_id=lr_id,
                    asset_ids=[],
                    immich_stack_id=immich_stack_id,
                )
            )

    return actions


async def apply_stack_sync(
    actions: StackPlan,
    client: ImmichClient,
    state: StateDB,
) -> StacksResult:
    result = StacksResult()

    for action in actions:
        match action.kind:
            case "create":
                resp = await client.create_stack(action.asset_ids)
                state.set_meta(f"stack:{action.lr_stack_id}", resp["id"])
                state.append_audit_log(
                    "create_stack",
                    "stack",
                    resp["id"],
                    {"assets": len(action.asset_ids)},
                )
                result.created += 1
            case "update":
                await client.delete_stack(action.immich_stack_id)
                resp = await client.create_stack(action.asset_ids)
                state.set_meta(f"stack:{action.lr_stack_id}", resp["id"])
                state.append_audit_log(
                    "update_stack",
                    "stack",
                    resp["id"],
                    {"assets": len(action.asset_ids)},
                )
                result.updated += 1
            case "delete":
                try:
                    await client.delete_stack(action.immich_stack_id)
                except Exception:
                    logger.warning(
                        "delete_stack_failed",
                        stack_id=action.immich_stack_id,
                    )
                state.set_meta(f"stack:{action.lr_stack_id}", "")
                state.append_audit_log(
                    "delete_stack",
                    "stack",
                    action.immich_stack_id,
                )
                result.deleted += 1

    return result


class Step:
    name = "stacks"
    status_msg = "Syncing stacks..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.stacks

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> StackPlan:
        lr_stacks = read_stacks(ctx.catalog.catalog)
        actions = await plan_stack_sync(lr_stacks, ctx.resolved, ctx.state, ctx.client)
        summary.stacks = StacksResult(
            created=sum(1 for a in actions if a.kind == "create"),
            updated=sum(1 for a in actions if a.kind == "update"),
            deleted=sum(1 for a in actions if a.kind == "delete"),
        )
        return actions

    async def apply(self, plan: StackPlan, ctx: SyncContext) -> None:
        if ctx.dry_run:
            return
        await apply_stack_sync(plan, ctx.client, ctx.state)
