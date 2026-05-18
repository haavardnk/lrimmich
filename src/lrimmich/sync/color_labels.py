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

COLOR_TAG_PREFIX = "lr:color:"
VALID_COLORS = {"Red", "Yellow", "Green", "Blue", "Purple"}
ColorLabelsPlan = tuple[list[TagAction], dict[str, str]]


def plan_color_labels_sync(
    labels: dict[str, str],
    resolved: dict[str, str],
    tag_map: TagMap,
    state: StateDB,
) -> list[TagAction]:
    previous = state.get_meta("color_labels_snapshot")
    prev_assignments: dict[str, str] = json.loads(previous) if previous else {}

    desired: dict[str, str] = {}
    for rp, color in labels.items():
        key = color.lower()
        if rp in resolved and key in tag_map:
            desired[resolved[rp]] = key

    by_tag_add: dict[str, list[str]] = {}
    by_tag_remove: dict[str, list[str]] = {}

    for asset_id, color in desired.items():
        old_color = prev_assignments.get(asset_id)
        if old_color == color:
            continue
        if old_color and old_color in tag_map:
            by_tag_remove.setdefault(old_color, []).append(asset_id)
        by_tag_add.setdefault(color, []).append(asset_id)

    for asset_id, old_color in prev_assignments.items():
        if asset_id not in desired and old_color in tag_map:
            by_tag_remove.setdefault(old_color, []).append(asset_id)

    return build_tag_actions(by_tag_add, by_tag_remove, tag_map, COLOR_TAG_PREFIX)


def apply_color_labels_sync(
    actions: list[TagAction],
    desired: dict[str, str],
    client: ImmichClient,
    state: StateDB,
) -> ColorLabelsResult:
    return apply_tag_actions(
        actions, desired, client, state, "color_labels_snapshot", "sync_color_labels"
    )


class Step:
    name = "color_labels"
    status_msg = "Syncing color labels..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.tags

    def plan(self, ctx: SyncContext, summary: SyncSummary) -> ColorLabelsPlan:
        labels = read_color_labels(ctx.cfg.lightroom.catalog)
        tag_map = ensure_tags(
            ctx.client,
            ctx.get_existing_tags(),
            {c.lower() for c in VALID_COLORS},
            COLOR_TAG_PREFIX,
            create=not ctx.dry_run,
        )
        actions = plan_color_labels_sync(labels, ctx.resolved, tag_map, ctx.state)
        desired = {
            ctx.resolved[rp]: color.lower()
            for rp, color in labels.items()
            if rp in ctx.resolved and color.lower() in tag_map
        }
        summary.color_labels = ColorLabelsResult(
            tagged=sum(len(a.asset_ids) for a in actions if a.kind == "tag"),
            untagged=sum(len(a.asset_ids) for a in actions if a.kind == "untag"),
        )
        return actions, desired

    def apply(self, plan: ColorLabelsPlan, ctx: SyncContext) -> None:
        apply_color_labels_sync(plan[0], plan[1], ctx.client, ctx.state)
