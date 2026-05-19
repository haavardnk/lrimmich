from dataclasses import dataclass, field
from fnmatch import fnmatch

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.config import (
    AlbumFilter,
    AlbumMode,
    AlbumRule,
    AssetOrder,
    Config,
    SafetyConfig,
)


def format_album_name(collection: LrCollection, fmt: str = "{path}") -> str:
    parts = collection.full_name.split("/")
    return fmt.format(
        path=collection.full_name,
        name=parts[-1],
        parent=parts[-2] if len(parts) >= 2 else "",
    )


class AlbumSyncError(Exception):
    pass


class RemoveLimitExceeded(AlbumSyncError):
    def __init__(self, album_name: str, count: int, percent: int, limit: int) -> None:
        self.album_name = album_name
        self.count = count
        self.percent = percent
        self.limit = limit
        super().__init__(
            f"Removing {count} assets ({percent}%) from "
            f"'{album_name}' exceeds {limit}% limit"
        )


class DeleteThresholdExceeded(AlbumSyncError):
    def __init__(self, count: int, threshold: int) -> None:
        self.count = count
        self.threshold = threshold
        super().__init__(f"Deleting {count} albums exceeds threshold of {threshold}")


@dataclass
class AlbumAction:
    kind: str
    lr_collection_id: int
    album_name: str
    immich_album_id: str | None = None
    asset_ids: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    old_name: str = ""
    description: str | None = None
    order: AssetOrder | None = None


@dataclass
class AlbumRuleResult:
    filter: AlbumFilter
    min_rating: int
    description: str | None
    order: AssetOrder | None
    share_with: list[str] | None


def resolve_album_rule(
    collection: LrCollection,
    album_filter: AlbumFilter,
    album_min_rating: int,
    album_rules: list[AlbumRule] | None,
) -> AlbumRuleResult:
    for rule in album_rules or []:
        if (rule.id is not None and rule.id == collection.id) or (
            rule.match and fnmatch(collection.full_name, rule.match)
        ):
            return AlbumRuleResult(
                filter=rule.filter or album_filter,
                min_rating=rule.min_rating
                if rule.min_rating is not None
                else album_min_rating,
                description=rule.description,
                order=rule.order,
                share_with=rule.share_with,
            )
    return AlbumRuleResult(
        filter=album_filter,
        min_rating=album_min_rating,
        description=None,
        order=None,
        share_with=None,
    )


def _filtered_asset_ids(
    collection: LrCollection,
    resolved: dict[str, str],
    album_filter: AlbumFilter,
    album_min_rating: int,
    album_rules: list[AlbumRule] | None,
    flagged_paths: set[str],
    rejected_paths: set[str],
    rated_paths: dict[str, int],
) -> list[str]:
    rule = resolve_album_rule(collection, album_filter, album_min_rating, album_rules)
    paths = collection.relative_paths
    if rule.filter == "flagged":
        paths = [p for p in paths if p in flagged_paths]
    elif rule.filter == "unflagged":
        paths = [p for p in paths if p not in rejected_paths]
    elif rule.filter == "rejected":
        paths = [p for p in paths if p in rejected_paths]
    if rule.min_rating > 0:
        paths = [p for p in paths if rated_paths.get(p, 0) >= rule.min_rating]
    return [resolved[p] for p in paths if p in resolved]


@dataclass
class AlbumPlanContext:
    collections: list[LrCollection]
    resolved: dict[str, str]
    state: StateDB
    client: ImmichClient
    share_with: list[str]
    safety: SafetyConfig
    force: bool
    no_delete: bool
    skip_empty: bool
    album_name_format: str
    album_mode: AlbumMode
    album_filter: AlbumFilter
    album_min_rating: int
    album_rules: list[AlbumRule]
    flagged_paths: set[str]
    rejected_paths: set[str]
    rated_paths: dict[str, int]


async def _plan_collection(
    collection: LrCollection,
    ctx: AlbumPlanContext,
    all_albums: dict[str, dict],
) -> tuple[list[AlbumAction], bool]:
    album_name = format_album_name(collection, ctx.album_name_format)
    rule = resolve_album_rule(
        collection, ctx.album_filter, ctx.album_min_rating, ctx.album_rules
    )
    effective_share = rule.share_with if rule.share_with is not None else ctx.share_with
    asset_ids = _filtered_asset_ids(
        collection,
        ctx.resolved,
        ctx.album_filter,
        ctx.album_min_rating,
        ctx.album_rules,
        ctx.flagged_paths,
        ctx.rejected_paths,
        ctx.rated_paths,
    )
    ownership = ctx.state.get_album_ownership(collection.id)
    actions: list[AlbumAction] = []

    if ctx.skip_empty and not asset_ids:
        return actions, True

    if ownership is None:
        actions.append(
            AlbumAction(
                kind="create",
                lr_collection_id=collection.id,
                album_name=album_name,
                asset_ids=asset_ids,
                description=rule.description,
                order=rule.order,
            )
        )
        if effective_share:
            actions.append(
                AlbumAction(
                    kind="share",
                    lr_collection_id=collection.id,
                    album_name=album_name,
                    user_ids=list(effective_share),
                )
            )
        return actions, False

    immich_album_id = ownership["immich_album_id"]

    if ownership["last_name"] != album_name:
        actions.append(
            AlbumAction(
                kind="rename",
                lr_collection_id=collection.id,
                immich_album_id=immich_album_id,
                album_name=album_name,
                old_name=ownership["last_name"],
            )
        )

    last_desc = ctx.state.get_meta(f"album_desc:{collection.id}")
    if rule.description != last_desc:
        actions.append(
            AlbumAction(
                kind="set_description",
                lr_collection_id=collection.id,
                immich_album_id=immich_album_id,
                album_name=album_name,
                description=rule.description,
            )
        )

    last_order = ctx.state.get_meta(f"album_order:{collection.id}")
    if rule.order and rule.order != last_order:
        actions.append(
            AlbumAction(
                kind="set_order",
                lr_collection_id=collection.id,
                immich_album_id=immich_album_id,
                album_name=album_name,
                order=rule.order,
            )
        )

    actions.extend(
        await _plan_diff(collection, ctx, immich_album_id, album_name, asset_ids)
    )

    if effective_share:
        actions.extend(
            _plan_share(
                effective_share, immich_album_id, album_name, collection.id, all_albums
            )
        )

    return actions, False


async def _plan_diff(
    collection: LrCollection,
    ctx: AlbumPlanContext,
    immich_album_id: str,
    album_name: str,
    asset_ids: list[str],
) -> list[AlbumAction]:
    actions: list[AlbumAction] = []
    album_data = await ctx.client.get_album(immich_album_id)
    current_ids = {a["id"] for a in album_data.get("assets", [])}
    desired_ids = set(asset_ids)

    to_add = sorted(desired_ids - current_ids)

    if ctx.album_mode == "hybrid":
        tracked_ids = ctx.state.get_synced_album_assets(immich_album_id)
        if not tracked_ids:
            actions.append(
                AlbumAction(
                    kind="track_assets",
                    lr_collection_id=collection.id,
                    immich_album_id=immich_album_id,
                    album_name=album_name,
                    asset_ids=sorted(desired_ids),
                )
            )
            to_remove: list[str] = []
        else:
            to_remove = sorted((tracked_ids - desired_ids) & current_ids)
    else:
        to_remove = sorted(current_ids - desired_ids)

    if to_add:
        actions.append(
            AlbumAction(
                kind="add_assets",
                lr_collection_id=collection.id,
                immich_album_id=immich_album_id,
                album_name=album_name,
                asset_ids=to_add,
            )
        )

    if to_remove:
        total = len(current_ids)
        pct = len(to_remove) * 100 // total if total > 0 else 0
        if pct > ctx.safety.remove_percent_limit and not ctx.force:
            raise RemoveLimitExceeded(
                album_name,
                len(to_remove),
                pct,
                ctx.safety.remove_percent_limit,
            )
        actions.append(
            AlbumAction(
                kind="remove_assets",
                lr_collection_id=collection.id,
                immich_album_id=immich_album_id,
                album_name=album_name,
                asset_ids=to_remove,
            )
        )

    return actions


def _plan_share(
    share_with: list[str],
    immich_album_id: str,
    album_name: str,
    lr_collection_id: int,
    all_albums: dict[str, dict],
) -> list[AlbumAction]:
    album_summary = all_albums.get(immich_album_id, {})
    shared_ids = {u["user"]["id"] for u in album_summary.get("albumUsers", [])}
    unshared = [uid for uid in share_with if uid not in shared_ids]
    if not unshared:
        return []
    return [
        AlbumAction(
            kind="share",
            lr_collection_id=lr_collection_id,
            immich_album_id=immich_album_id,
            album_name=album_name,
            user_ids=unshared,
        )
    ]


def _plan_delete_orphans(ctx: AlbumPlanContext, lr_ids: set[int]) -> list[AlbumAction]:
    owned = ctx.state.get_all_owned_albums()
    to_delete = [o for o in owned if o["lr_collection_id"] not in lr_ids]
    if not to_delete or ctx.no_delete or ctx.safety.disable_deletes:
        return []
    if len(to_delete) > ctx.safety.delete_threshold and not ctx.force:
        raise DeleteThresholdExceeded(len(to_delete), ctx.safety.delete_threshold)
    return [
        AlbumAction(
            kind="delete",
            lr_collection_id=o["lr_collection_id"],
            immich_album_id=o["immich_album_id"],
            album_name=o["last_name"],
        )
        for o in to_delete
    ]


async def plan_album_sync(
    collections: list[LrCollection],
    resolved: dict[str, str],
    state: StateDB,
    client: ImmichClient,
    album_filter: AlbumFilter = "all",
    album_min_rating: int = 0,
    album_mode: AlbumMode = "managed",
    album_name_format: str = "{path}",
    album_rules: list[AlbumRule] | None = None,
    flagged_paths: set[str] | None = None,
    force: bool = False,
    no_delete: bool = False,
    rated_paths: dict[str, int] | None = None,
    rejected_paths: set[str] | None = None,
    safety: SafetyConfig | None = None,
    share_with: list[str] | None = None,
    skip_empty: bool = True,
) -> list[AlbumAction]:
    ctx = AlbumPlanContext(
        collections=collections,
        resolved=resolved,
        state=state,
        client=client,
        share_with=share_with or [],
        safety=safety or SafetyConfig(),
        force=force,
        no_delete=no_delete,
        skip_empty=skip_empty,
        album_name_format=album_name_format,
        album_mode=album_mode,
        album_filter=album_filter,
        album_min_rating=album_min_rating,
        album_rules=album_rules or [],
        flagged_paths=flagged_paths or set(),
        rejected_paths=rejected_paths or set(),
        rated_paths=rated_paths or {},
    )

    needs_share = bool(ctx.share_with) or any(r.share_with for r in ctx.album_rules)
    all_albums = {a["id"]: a for a in await client.get_albums()} if needs_share else {}

    actions: list[AlbumAction] = []
    lr_ids = {c.id for c in collections}

    for collection in collections:
        col_actions, empty = await _plan_collection(collection, ctx, all_albums)
        if empty:
            lr_ids.discard(collection.id)
        actions.extend(col_actions)

    actions.extend(_plan_delete_orphans(ctx, lr_ids))
    return actions


async def _apply_create(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> str:
    result = await client.create_album(
        action.album_name, action.asset_ids, description=action.description or ""
    )
    album_id: str = result["id"]
    if action.order:
        await client.update_album(album_id, order=action.order)
        state.set_meta(f"album_order:{action.lr_collection_id}", action.order)
    state.upsert_album_ownership(action.lr_collection_id, album_id, action.album_name)
    state.replace_synced_album_assets(album_id, set(action.asset_ids))
    if action.description:
        state.set_meta(f"album_desc:{action.lr_collection_id}", action.description)
    state.append_audit_log(
        "create_album",
        "album",
        album_id,
        {"name": action.album_name, "assets": len(action.asset_ids)},
    )
    return album_id


async def _apply_rename(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id:
        return
    await client.update_album(action.immich_album_id, albumName=action.album_name)
    state.upsert_album_ownership(
        action.lr_collection_id, action.immich_album_id, action.album_name
    )
    state.append_audit_log(
        "rename_album",
        "album",
        action.immich_album_id,
        {"old": action.old_name, "new": action.album_name},
    )


async def _apply_add_assets(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id:
        return
    await client.add_album_assets(action.immich_album_id, action.asset_ids)
    state.add_synced_album_assets(action.immich_album_id, set(action.asset_ids))
    state.append_audit_log(
        "add_assets",
        "album",
        action.immich_album_id,
        {"count": len(action.asset_ids)},
    )


async def _apply_remove_assets(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id:
        return
    await client.remove_album_assets(action.immich_album_id, action.asset_ids)
    state.remove_synced_album_assets(action.immich_album_id, set(action.asset_ids))
    state.append_audit_log(
        "remove_assets",
        "album",
        action.immich_album_id,
        {"count": len(action.asset_ids)},
    )


async def _apply_share(
    action: AlbumAction,
    client: ImmichClient,
    state: StateDB,
    created: dict[int, str],
) -> None:
    album_id = action.immich_album_id or created.get(action.lr_collection_id)
    if not album_id:
        return
    await client.add_album_users(album_id, action.user_ids)
    state.append_audit_log("share_album", "album", album_id, {"users": action.user_ids})


async def _apply_delete(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id:
        return
    await client.delete_album(action.immich_album_id)
    state.remove_album_ownership(action.lr_collection_id)
    state.clear_synced_album_assets(action.immich_album_id)
    state.append_audit_log(
        "delete_album", "album", action.immich_album_id, {"name": action.album_name}
    )


def _apply_track_assets(action: AlbumAction, state: StateDB) -> None:
    if not action.immich_album_id:
        return
    state.replace_synced_album_assets(action.immich_album_id, set(action.asset_ids))


async def _apply_set_description(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id:
        return
    await client.update_album(
        action.immich_album_id, description=action.description or ""
    )
    meta_key = f"album_desc:{action.lr_collection_id}"
    if action.description:
        state.set_meta(meta_key, action.description)
    else:
        state.set_meta(meta_key, "")


async def _apply_set_order(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id or not action.order:
        return
    await client.update_album(action.immich_album_id, order=action.order)
    state.set_meta(f"album_order:{action.lr_collection_id}", action.order)


async def apply_album_sync(
    actions: list[AlbumAction],
    client: ImmichClient,
    state: StateDB,
) -> None:
    created: dict[int, str] = {}

    for action in actions:
        match action.kind:
            case "create":
                created[action.lr_collection_id] = await _apply_create(
                    action, client, state
                )
            case "rename":
                await _apply_rename(action, client, state)
            case "add_assets":
                await _apply_add_assets(action, client, state)
            case "remove_assets":
                await _apply_remove_assets(action, client, state)
            case "share":
                await _apply_share(action, client, state, created)
            case "delete":
                await _apply_delete(action, client, state)
            case "track_assets":
                _apply_track_assets(action, state)
            case "set_description":
                await _apply_set_description(action, client, state)
            case "set_order":
                await _apply_set_order(action, client, state)


def count_album_actions(actions: list[AlbumAction]) -> dict[str, int]:
    counts: dict[str, int] = {
        "created": 0,
        "renamed": 0,
        "deleted": 0,
        "assets_added": 0,
        "assets_removed": 0,
    }
    for a in actions:
        match a.kind:
            case "create":
                counts["created"] += 1
            case "rename":
                counts["renamed"] += 1
            case "delete":
                counts["deleted"] += 1
            case "add_assets":
                counts["assets_added"] += len(a.asset_ids)
            case "remove_assets":
                counts["assets_removed"] += len(a.asset_ids)
    return counts


class Step:
    name = "albums"
    status_msg = "Syncing albums..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.albums

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> list[AlbumAction]:
        needs_flagged = ctx.cfg.sync.album_filter == "flagged" or any(
            r.filter == "flagged" for r in ctx.cfg.album_rules
        )
        needs_rejected = ctx.cfg.sync.album_filter in (
            "unflagged",
            "rejected",
        ) or any(r.filter in ("unflagged", "rejected") for r in ctx.cfg.album_rules)
        needs_rated = ctx.cfg.sync.album_min_rating > 0 or any(
            (r.min_rating or 0) > 0 for r in ctx.cfg.album_rules
        )
        actions = await plan_album_sync(
            ctx.collections,
            ctx.resolved,
            ctx.state,
            ctx.client,
            album_filter=ctx.cfg.sync.album_filter,
            album_min_rating=ctx.cfg.sync.album_min_rating,
            album_mode=ctx.cfg.sync.album_mode,
            album_name_format=ctx.cfg.sync.album_name_format,
            album_rules=ctx.cfg.album_rules,
            flagged_paths=ctx.get_flagged() if needs_flagged else None,
            force=ctx.force,
            no_delete=ctx.no_delete,
            rated_paths=ctx.get_rated() if needs_rated else None,
            rejected_paths=ctx.get_rejected() if needs_rejected else None,
            safety=ctx.cfg.safety,
            share_with=ctx.cfg.sync.share_albums_with,
            skip_empty=ctx.cfg.sync.skip_empty,
        )
        counts = count_album_actions(actions)
        summary.albums_created = counts["created"]
        summary.albums_renamed = counts["renamed"]
        summary.albums_deleted = counts["deleted"]
        summary.assets_added = counts["assets_added"]
        summary.assets_removed = counts["assets_removed"]
        return actions

    async def apply(self, plan: list[AlbumAction], ctx: SyncContext) -> None:
        await apply_album_sync(plan, ctx.client, ctx.state)
