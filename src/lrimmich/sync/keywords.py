import json

from lrimmich.clients.catalog import read_keywords
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import KeywordsResult, SyncSummary
from lrimmich.sync.tags import (
    TagAction,
    TagMap,
    apply_tag_actions,
    build_tag_actions,
    ensure_tags,
)
from lrimmich.utils.config import Config

KEYWORD_TAG_PREFIX = "lr:keyword:"
KeywordsPlan = tuple[list[TagAction], dict[str, list[str]]]


def plan_keywords_sync(
    keywords: dict[str, list[str]],
    resolved: dict[str, str],
    tag_map: TagMap,
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


class Step:
    name = "keywords"
    status_msg = "Syncing keywords..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.tags

    def plan(self, ctx: SyncContext, summary: SyncSummary) -> KeywordsPlan:
        kw_data = read_keywords(ctx.cfg.lightroom.catalog)
        needed_kws: set[str] = set()
        for kws in kw_data.values():
            needed_kws.update(kws)
        kw_tag_map = ensure_tags(
            ctx.client,
            ctx.get_existing_tags(),
            needed_kws,
            KEYWORD_TAG_PREFIX,
            create=not ctx.dry_run,
        )
        kw_actions = plan_keywords_sync(kw_data, ctx.resolved, kw_tag_map, ctx.state)
        kw_desired: dict[str, list[str]] = {}
        for rp, kws in kw_data.items():
            if rp in ctx.resolved:
                valid = sorted(k for k in kws if k in kw_tag_map)
                if valid:
                    kw_desired[ctx.resolved[rp]] = valid
        summary.keywords = KeywordsResult(
            tagged=sum(len(a.asset_ids) for a in kw_actions if a.kind == "tag"),
            untagged=sum(len(a.asset_ids) for a in kw_actions if a.kind == "untag"),
        )
        return kw_actions, kw_desired

    def apply(self, plan: KeywordsPlan, ctx: SyncContext) -> None:
        apply_keywords_sync(plan[0], plan[1], ctx.client, ctx.state)
