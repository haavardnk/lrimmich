import json

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.tags import (
    TagAction,
    TagMap,
    TagSyncResult,
    apply_tag_actions,
    build_tag_actions,
)

COLOR_TAG_PREFIX = "lr:color:"
VALID_COLORS = {"Red", "Yellow", "Green", "Blue", "Purple"}

ColorLabelsResult = TagSyncResult


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
