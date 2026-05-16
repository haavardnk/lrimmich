import json

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.tags import (
    TagAction,
    TagSyncResult,
    apply_tag_actions,
    build_tag_actions,
    ensure_tags,
)

KEYWORD_TAG_PREFIX = "lr:keyword:"

KeywordsResult = TagSyncResult


def _ensure_keyword_tags(
    client: ImmichClient,
    existing_tags: list[dict[str, str]],
    needed: set[str],
    *,
    create: bool = True,
) -> dict[str, str]:
    return ensure_tags(client, existing_tags, needed, KEYWORD_TAG_PREFIX, create=create)


def plan_keywords_sync(
    keywords: dict[str, list[str]],
    resolved: dict[str, str],
    tag_map: dict[str, str],
    state: StateDB,
) -> list[TagAction]:
    previous = state.get_meta("keywords_snapshot")
    prev_assignments: dict[str, list[str]] = json.loads(previous) if previous else {}

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

    return build_tag_actions(by_tag_add, by_tag_remove, tag_map, KEYWORD_TAG_PREFIX)


def apply_keywords_sync(
    actions: list[TagAction],
    desired: dict[str, list[str]],
    client: ImmichClient,
    state: StateDB,
) -> KeywordsResult:
    return apply_tag_actions(
        actions, desired, client, state, "keywords_snapshot", "sync_keywords"
    )
