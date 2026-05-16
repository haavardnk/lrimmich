import json
from dataclasses import dataclass, field

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB

COLOR_TAG_PREFIX = "lr:color:"
VALID_COLORS = {"Red", "Yellow", "Green", "Blue", "Purple"}


@dataclass
class TagAction:
    kind: str
    tag_id: str
    tag_name: str
    asset_ids: list[str] = field(default_factory=list)


@dataclass
class ColorLabelsResult:
    tagged: int = 0
    untagged: int = 0


def _ensure_color_tags(
    client: ImmichClient,
    existing_tags: list[dict[str, str]],
) -> dict[str, str]:
    tag_map: dict[str, str] = {}
    existing_by_name = {t["value"]: t["id"] for t in existing_tags}
    for color in VALID_COLORS:
        tag_name = COLOR_TAG_PREFIX + color.lower()
        if tag_name in existing_by_name:
            tag_map[color] = existing_by_name[tag_name]
        else:
            result = client.create_tag(tag_name)
            tag_map[color] = result["id"]
    return tag_map


def plan_color_labels_sync(
    labels: dict[str, str],
    resolved: dict[str, str],
    tag_map: dict[str, str],
    state: StateDB,
) -> list[TagAction]:
    previous = state.get_meta("color_labels_snapshot")
    prev_assignments: dict[str, str] = {}
    if previous:
        prev_assignments = json.loads(previous)

    desired: dict[str, str] = {}
    for rp, color in labels.items():
        if rp in resolved and color in tag_map:
            desired[resolved[rp]] = color

    actions: list[TagAction] = []
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

    for color, asset_ids in sorted(by_tag_add.items()):
        actions.append(
            TagAction(
                kind="tag",
                tag_id=tag_map[color],
                tag_name=COLOR_TAG_PREFIX + color.lower(),
                asset_ids=sorted(asset_ids),
            )
        )

    for color, asset_ids in sorted(by_tag_remove.items()):
        actions.append(
            TagAction(
                kind="untag",
                tag_id=tag_map[color],
                tag_name=COLOR_TAG_PREFIX + color.lower(),
                asset_ids=sorted(asset_ids),
            )
        )

    return actions


def apply_color_labels_sync(
    actions: list[TagAction],
    desired: dict[str, str],
    client: ImmichClient,
    state: StateDB,
) -> ColorLabelsResult:
    tagged = 0
    untagged = 0
    for action in actions:
        if action.kind == "tag":
            client.tag_assets(action.tag_id, action.asset_ids)
            tagged += len(action.asset_ids)
        elif action.kind == "untag":
            client.untag_assets(action.tag_id, action.asset_ids)
            untagged += len(action.asset_ids)

    state.set_meta("color_labels_snapshot", json.dumps(desired))

    result = ColorLabelsResult(tagged=tagged, untagged=untagged)
    if tagged or untagged:
        state.append_audit_log(
            "sync_color_labels",
            "tags",
            payload={"tagged": tagged, "untagged": untagged},
        )
    return result
