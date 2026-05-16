import json
from dataclasses import dataclass, field

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB

KEYWORD_TAG_PREFIX = "lr:keyword:"


@dataclass
class TagAction:
    kind: str
    tag_id: str
    tag_name: str
    asset_ids: list[str] = field(default_factory=list)


@dataclass
class KeywordsResult:
    tagged: int = 0
    untagged: int = 0


def _ensure_keyword_tags(
    client: ImmichClient,
    existing_tags: list[dict[str, str]],
    needed: set[str],
    *,
    create: bool = True,
) -> dict[str, str]:
    existing_by_name = {t["value"]: t["id"] for t in existing_tags}
    tag_map: dict[str, str] = {}
    for keyword in sorted(needed):
        tag_name = KEYWORD_TAG_PREFIX + keyword
        if tag_name in existing_by_name:
            tag_map[keyword] = existing_by_name[tag_name]
        elif create:
            result = client.create_tag(tag_name)
            tag_map[keyword] = result["id"]
        else:
            tag_map[keyword] = f"pending:{tag_name}"
    return tag_map


def plan_keywords_sync(
    keywords: dict[str, list[str]],
    resolved: dict[str, str],
    tag_map: dict[str, str],
    state: StateDB,
) -> list[TagAction]:
    previous = state.get_meta("keywords_snapshot")
    prev_assignments: dict[str, list[str]] = {}
    if previous:
        prev_assignments = json.loads(previous)

    desired: dict[str, list[str]] = {}
    for rp, kws in keywords.items():
        if rp in resolved:
            asset_id = resolved[rp]
            valid = sorted(k for k in kws if k in tag_map)
            if valid:
                desired[asset_id] = valid

    by_tag_add: dict[str, list[str]] = {}
    by_tag_remove: dict[str, list[str]] = {}

    for asset_id, kws in desired.items():
        old_kws = set(prev_assignments.get(asset_id, []))
        new_kws = set(kws)
        for kw in new_kws - old_kws:
            by_tag_add.setdefault(kw, []).append(asset_id)
        for kw in old_kws - new_kws:
            if kw in tag_map:
                by_tag_remove.setdefault(kw, []).append(asset_id)

    for asset_id, old_kws in prev_assignments.items():
        if asset_id not in desired:
            for kw in old_kws:
                if kw in tag_map:
                    by_tag_remove.setdefault(kw, []).append(asset_id)

    actions: list[TagAction] = []
    for kw, asset_ids in sorted(by_tag_add.items()):
        actions.append(
            TagAction(
                kind="tag",
                tag_id=tag_map[kw],
                tag_name=KEYWORD_TAG_PREFIX + kw,
                asset_ids=sorted(asset_ids),
            )
        )
    for kw, asset_ids in sorted(by_tag_remove.items()):
        actions.append(
            TagAction(
                kind="untag",
                tag_id=tag_map[kw],
                tag_name=KEYWORD_TAG_PREFIX + kw,
                asset_ids=sorted(asset_ids),
            )
        )

    return actions


def apply_keywords_sync(
    actions: list[TagAction],
    desired: dict[str, list[str]],
    client: ImmichClient,
    state: StateDB,
) -> KeywordsResult:
    tagged = 0
    untagged = 0
    for action in actions:
        if action.kind == "tag":
            client.tag_assets(action.tag_id, action.asset_ids)
            tagged += len(action.asset_ids)
        elif action.kind == "untag":
            client.untag_assets(action.tag_id, action.asset_ids)
            untagged += len(action.asset_ids)

    state.set_meta("keywords_snapshot", json.dumps(desired))

    result = KeywordsResult(tagged=tagged, untagged=untagged)
    if tagged or untagged:
        state.append_audit_log(
            "sync_keywords",
            "tags",
            payload={"tagged": tagged, "untagged": untagged},
        )
    return result
