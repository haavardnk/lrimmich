from dataclasses import dataclass

from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import TagSyncResult

TagAssignments = dict[str, list[str]]


@dataclass
class TagAction:
    kind: str
    tag_name: str
    asset_ids: list[str]


@dataclass
class TagPlan:
    actions: list[TagAction]
    desired: TagAssignments

    @property
    def result(self) -> TagSyncResult:
        return TagSyncResult(
            tagged=sum(len(a.asset_ids) for a in self.actions if a.kind == "tag"),
            untagged=sum(len(a.asset_ids) for a in self.actions if a.kind == "untag"),
        )


def _group_actions(kind: str, pairs: set[tuple[str, str]]) -> list[TagAction]:
    by_name: dict[str, list[str]] = {}
    for asset_id, name in sorted(pairs):
        by_name.setdefault(name, []).append(asset_id)
    return [TagAction(kind, name, ids) for name, ids in sorted(by_name.items())]


def diff_tags(
    previous: TagAssignments, desired: TagAssignments, existing: set[str]
) -> list[TagAction]:
    old = {(a, name) for a, names in previous.items() for name in names}
    new = {(a, name) for a, names in desired.items() for name in names}
    removable = {(a, name) for a, name in old - new if name in existing}
    return _group_actions("tag", new - old) + _group_actions("untag", removable)


async def plan_tags(
    ctx: SyncContext, desired: TagAssignments, snapshot_key: str
) -> TagPlan:
    previous: TagAssignments = ctx.state.get_snapshot(snapshot_key) or {}
    existing = set(await ctx.get_tag_ids())
    return TagPlan(diff_tags(previous, desired, existing), desired)


async def apply_tags(
    ctx: SyncContext, plan: TagPlan, snapshot_key: str, audit_action: str
) -> None:
    tag_ids = await ctx.ensure_tags({a.tag_name for a in plan.actions})
    for action in plan.actions:
        if action.kind == "tag":
            await ctx.client.tag_assets(tag_ids[action.tag_name], action.asset_ids)
        else:
            await ctx.client.untag_assets(tag_ids[action.tag_name], action.asset_ids)
    ctx.state.set_snapshot(snapshot_key, plan.desired)
    result = plan.result
    if result.tagged or result.untagged:
        ctx.state.append_audit_log(
            audit_action,
            "tags",
            payload={"tagged": result.tagged, "untagged": result.untagged},
        )
