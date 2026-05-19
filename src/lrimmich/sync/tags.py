import json
from dataclasses import dataclass, field

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.summary import TagSyncResult

TagMap = dict[str, str | None]


@dataclass
class TagAction:
    kind: str
    tag_id: str
    tag_name: str
    asset_ids: list[str] = field(default_factory=list)


async def ensure_tags(
    client: ImmichClient,
    existing_tags: list[dict[str, str]],
    needed: set[str],
    prefix: str,
    *,
    create: bool = True,
) -> TagMap:
    existing_by_name = {t["value"]: t["id"] for t in existing_tags}
    tag_map: TagMap = {}
    for key in sorted(needed):
        tag_name = prefix + key
        if tag_name in existing_by_name:
            tag_map[key] = existing_by_name[tag_name]
        elif create:
            result = await client.create_tag(tag_name)
            tag_map[key] = result["id"]
        else:
            tag_map[key] = None
    return tag_map


def build_tag_actions(
    by_tag_add: dict[str, list[str]],
    by_tag_remove: dict[str, list[str]],
    tag_map: TagMap,
    prefix: str,
) -> list[TagAction]:
    actions: list[TagAction] = []
    for key, asset_ids in sorted(by_tag_add.items()):
        tag_id = tag_map.get(key)
        if tag_id is None:
            continue
        actions.append(
            TagAction(
                kind="tag",
                tag_id=tag_id,
                tag_name=prefix + key,
                asset_ids=sorted(asset_ids),
            )
        )
    for key, asset_ids in sorted(by_tag_remove.items()):
        tag_id = tag_map.get(key)
        if tag_id is None:
            continue
        actions.append(
            TagAction(
                kind="untag",
                tag_id=tag_id,
                tag_name=prefix + key,
                asset_ids=sorted(asset_ids),
            )
        )
    return actions


async def apply_tag_actions(
    actions: list[TagAction],
    desired: dict[str, str] | dict[str, list[str]],
    client: ImmichClient,
    state: StateDB,
    snapshot_key: str,
    audit_action: str,
) -> TagSyncResult:
    tagged = 0
    untagged = 0
    for action in actions:
        if action.kind == "tag":
            await client.tag_assets(action.tag_id, action.asset_ids)
            tagged += len(action.asset_ids)
        elif action.kind == "untag":
            await client.untag_assets(action.tag_id, action.asset_ids)
            untagged += len(action.asset_ids)

    state.set_meta(snapshot_key, json.dumps(desired))

    result = TagSyncResult(tagged=tagged, untagged=untagged)
    if tagged or untagged:
        state.append_audit_log(
            audit_action,
            "tags",
            payload={"tagged": tagged, "untagged": untagged},
        )
    return result
