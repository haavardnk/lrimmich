import json

from lrimmich.clients.catalog import read_color_labels
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import ColorLabelsResult, SyncSummary
from lrimmich.sync.tags import (
    TagAction,
    TagMap,
    apply_tag_actions,
    build_tag_actions,
    ensure_tags,
)
from lrimmich.utils.config import Config

DEFAULT_COLORS = ("red", "yellow", "green", "blue", "purple")
ColorLabelsPlan = tuple[list[TagAction], dict[str, str]]


def desired_color_tags(
    labels: dict[str, str],
    resolved: dict[str, str],
    overrides: dict[str, str],
) -> dict[str, str]:
    names = {c: c for c in DEFAULT_COLORS} | {
        label.lower(): tag for label, tag in overrides.items()
    }
    return {
        resolved[rp]: names[label.lower()]
        for rp, label in labels.items()
        if rp in resolved and label.lower() in names
    }


def plan_color_labels_sync(
    desired: dict[str, str],
    tag_map: TagMap,
    state: StateDB,
    prefix: str = "lr:color:",
) -> list[TagAction]:
    previous = state.get_meta("color_labels_snapshot")
    prev_assignments: dict[str, str] = json.loads(previous) if previous else {}

    by_tag_add: dict[str, list[str]] = {}
    by_tag_remove: dict[str, list[str]] = {}

    for asset_id, tag in desired.items():
        old_tag = prev_assignments.get(asset_id)
        if old_tag == tag:
            continue
        if old_tag:
            by_tag_remove.setdefault(old_tag, []).append(asset_id)
        by_tag_add.setdefault(tag, []).append(asset_id)

    for asset_id, old_tag in prev_assignments.items():
        if asset_id not in desired:
            by_tag_remove.setdefault(old_tag, []).append(asset_id)

    return build_tag_actions(by_tag_add, by_tag_remove, tag_map, prefix)


async def apply_color_labels_sync(
    actions: list[TagAction],
    desired: dict[str, str],
    client: ImmichClient,
    state: StateDB,
) -> ColorLabelsResult:
    return await apply_tag_actions(
        actions, desired, client, state, "color_labels_snapshot", "sync_color_labels"
    )


class Step:
    name = "color_labels"
    status_msg = "Syncing color labels..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.tags

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> ColorLabelsPlan:
        prefix = ctx.cfg.sync.color_prefix or ""
        desired = desired_color_tags(
            read_color_labels(ctx.catalog.catalog),
            ctx.resolved,
            ctx.cfg.sync.color_tags,
        )
        previous = ctx.state.get_meta("color_labels_snapshot")
        needed = set(desired.values())
        needed.update(json.loads(previous).values() if previous else [])
        tag_map = await ensure_tags(
            ctx.client,
            await ctx.get_existing_tags(),
            needed,
            prefix,
            create=not ctx.dry_run,
        )
        actions = plan_color_labels_sync(desired, tag_map, ctx.state, prefix)
        summary.color_labels = ColorLabelsResult(
            tagged=sum(len(a.asset_ids) for a in actions if a.kind == "tag"),
            untagged=sum(len(a.asset_ids) for a in actions if a.kind == "untag"),
        )
        return actions, desired

    async def apply(self, plan: ColorLabelsPlan, ctx: SyncContext) -> None:
        await apply_color_labels_sync(plan[0], plan[1], ctx.client, ctx.state)
