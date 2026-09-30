import asyncio
from dataclasses import dataclass, field
from fnmatch import fnmatch

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.config import AlbumFilter, AlbumRule, AssetOrder, Config

ALBUM_CONCURRENCY = 10


def format_album_name(collection: LrCollection, fmt: str = "{path}") -> str:
    parts = collection.full_name.split("/")
    return fmt.format(
        path=collection.full_name,
        name=parts[-1],
        parent=parts[-2] if len(parts) >= 2 else "",
    )


class AlbumSyncError(Exception):
    pass


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


def album_paths(
    collection: LrCollection,
    rule: AlbumRuleResult,
    flagged_paths: set[str],
    rejected_paths: set[str],
    rated_paths: dict[str, int],
) -> list[str]:
    paths = collection.relative_paths
    if rule.filter == "flagged":
        paths = [p for p in paths if p in flagged_paths]
    elif rule.filter == "unflagged":
        paths = [p for p in paths if p not in rejected_paths]
    elif rule.filter == "rejected":
        paths = [p for p in paths if p in rejected_paths]
    if rule.min_rating > 0:
        paths = [p for p in paths if rated_paths.get(p, 0) >= rule.min_rating]
    return paths


async def _fetch_album_assets(
    album_ids: list[str], client: ImmichClient
) -> dict[str, set[str]]:
    if not album_ids:
        return {}
    sem = asyncio.Semaphore(ALBUM_CONCURRENCY)

    async def _fetch(album_id: str) -> tuple[str, set[str]]:
        async with sem:
            return album_id, await client.get_album_asset_ids(album_id)

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_fetch(aid)) for aid in album_ids]
    return dict(t.result() for t in tasks)


def _plan_collection(
    collection: LrCollection,
    ctx: SyncContext,
    all_albums: dict[str, dict],
    album_assets: dict[str, set[str]],
    rule: AlbumRuleResult,
    asset_ids: list[str],
) -> list[AlbumAction]:
    album_name = format_album_name(collection, ctx.cfg.sync.album_name_format)
    effective_share = (
        rule.share_with
        if rule.share_with is not None
        else ctx.cfg.sync.share_albums_with
    )
    ownership = ctx.state.get_album_ownership(collection.id)
    actions: list[AlbumAction] = []

    if ownership is None or ownership["immich_album_id"] not in all_albums:
        actions.append(
            AlbumAction(
                kind="create",
                lr_collection_id=collection.id,
                album_name=album_name,
                immich_album_id=ownership["immich_album_id"] if ownership else None,
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
        return actions

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
        _plan_diff(
            collection,
            ctx,
            immich_album_id,
            album_name,
            album_assets.get(immich_album_id, set()),
            asset_ids,
        )
    )

    if effective_share:
        actions.extend(
            _plan_share(
                effective_share, immich_album_id, album_name, collection.id, all_albums
            )
        )

    return actions


def _plan_diff(
    collection: LrCollection,
    ctx: SyncContext,
    immich_album_id: str,
    album_name: str,
    current_ids: set[str],
    asset_ids: list[str],
) -> list[AlbumAction]:
    actions: list[AlbumAction] = []
    desired_ids = set(asset_ids)

    to_add = sorted(desired_ids - current_ids)

    if ctx.cfg.sync.album_mode == "hybrid":
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
        limit = ctx.cfg.safety.remove_percent_limit
        if pct > limit and not ctx.force:
            raise AlbumSyncError(
                f"Removing {len(to_remove)} assets ({pct}%) from "
                f"'{album_name}' exceeds {limit}% limit"
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


def _plan_delete_orphans(
    ctx: SyncContext, lr_ids: set[int], all_albums: dict[str, dict]
) -> list[AlbumAction]:
    safety = ctx.cfg.safety
    orphans = [
        o
        for o in ctx.state.get_all_owned_albums()
        if o["lr_collection_id"] not in lr_ids
    ]
    actions = [
        AlbumAction(
            kind="forget",
            lr_collection_id=o["lr_collection_id"],
            immich_album_id=o["immich_album_id"],
            album_name=o["last_name"],
        )
        for o in orphans
        if o["immich_album_id"] not in all_albums
    ]
    to_delete = [o for o in orphans if o["immich_album_id"] in all_albums]
    if not to_delete or ctx.no_delete or safety.disable_deletes:
        return actions
    if len(to_delete) > safety.delete_threshold and not ctx.force:
        raise AlbumSyncError(
            f"Deleting {len(to_delete)} albums exceeds threshold of "
            f"{safety.delete_threshold}"
        )
    return actions + [
        AlbumAction(
            kind="delete",
            lr_collection_id=o["lr_collection_id"],
            immich_album_id=o["immich_album_id"],
            album_name=o["last_name"],
        )
        for o in to_delete
    ]


async def plan_album_sync(ctx: SyncContext) -> list[AlbumAction]:
    sync = ctx.cfg.sync
    rules = {
        c.id: resolve_album_rule(
            c, sync.album_filter, sync.album_min_rating, ctx.cfg.album_rules
        )
        for c in ctx.collections
    }
    filters = {r.filter for r in rules.values()}
    flagged = ctx.flagged if "flagged" in filters else set()
    rejected = ctx.rejected if filters & {"unflagged", "rejected"} else set()
    rated = ctx.rated if any(r.min_rating for r in rules.values()) else {}
    asset_ids = {
        c.id: [
            ctx.resolved[p]
            for p in album_paths(c, rules[c.id], flagged, rejected, rated)
            if p in ctx.resolved
        ]
        for c in ctx.collections
    }
    kept = [c for c in ctx.collections if asset_ids[c.id] or not sync.skip_empty]

    all_albums = {a["id"]: a for a in await ctx.client.get_albums()}
    album_assets = await _fetch_album_assets(
        [
            ownership["immich_album_id"]
            for c in kept
            if (ownership := ctx.state.get_album_ownership(c.id)) is not None
            and all_albums.get(ownership["immich_album_id"], {}).get("assetCount")
        ],
        ctx.client,
    )

    actions = [
        action
        for c in kept
        for action in _plan_collection(
            c, ctx, all_albums, album_assets, rules[c.id], asset_ids[c.id]
        )
    ]
    actions.extend(_plan_delete_orphans(ctx, {c.id for c in kept}, all_albums))
    return actions


async def _apply_create(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> str:
    result = await client.create_album(
        action.album_name, action.asset_ids, description=action.description or ""
    )
    album_id: str = result["id"]
    if action.immich_album_id:
        state.clear_synced_album_assets(action.immich_album_id)
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
    action: AlbumAction, album_id: str, client: ImmichClient, state: StateDB
) -> None:
    await client.update_album(album_id, albumName=action.album_name)
    state.upsert_album_ownership(action.lr_collection_id, album_id, action.album_name)
    state.append_audit_log(
        "rename_album",
        "album",
        album_id,
        {"old": action.old_name, "new": action.album_name},
    )


async def _apply_add_assets(
    action: AlbumAction, album_id: str, client: ImmichClient, state: StateDB
) -> None:
    await client.add_album_assets(album_id, action.asset_ids)
    state.add_synced_album_assets(album_id, set(action.asset_ids))
    state.append_audit_log(
        "add_assets", "album", album_id, {"count": len(action.asset_ids)}
    )


async def _apply_remove_assets(
    action: AlbumAction, album_id: str, client: ImmichClient, state: StateDB
) -> None:
    await client.remove_album_assets(album_id, action.asset_ids)
    state.remove_synced_album_assets(album_id, set(action.asset_ids))
    state.append_audit_log(
        "remove_assets", "album", album_id, {"count": len(action.asset_ids)}
    )


async def _apply_share(
    action: AlbumAction, album_id: str, client: ImmichClient, state: StateDB
) -> None:
    await client.add_album_users(album_id, action.user_ids)
    state.append_audit_log("share_album", "album", album_id, {"users": action.user_ids})


async def _apply_delete(
    action: AlbumAction, album_id: str, client: ImmichClient, state: StateDB
) -> None:
    await client.delete_album(album_id)
    _apply_forget(action, album_id, state, "delete_album")


def _apply_forget(
    action: AlbumAction, album_id: str, state: StateDB, audit_action: str
) -> None:
    state.remove_album_ownership(action.lr_collection_id)
    state.clear_synced_album_assets(album_id)
    state.append_audit_log(audit_action, "album", album_id, {"name": action.album_name})


async def _apply_set_description(
    action: AlbumAction, album_id: str, client: ImmichClient, state: StateDB
) -> None:
    await client.update_album(album_id, description=action.description or "")
    state.set_meta(f"album_desc:{action.lr_collection_id}", action.description or "")


async def _apply_set_order(
    action: AlbumAction, album_id: str, client: ImmichClient, state: StateDB
) -> None:
    if not action.order:
        return
    await client.update_album(album_id, order=action.order)
    state.set_meta(f"album_order:{action.lr_collection_id}", action.order)


async def apply_album_sync(
    actions: list[AlbumAction],
    client: ImmichClient,
    state: StateDB,
) -> None:
    created: dict[int, str] = {}

    for action in actions:
        if action.kind == "create":
            created[action.lr_collection_id] = await _apply_create(
                action, client, state
            )
            continue
        album_id = action.immich_album_id or created.get(action.lr_collection_id)
        if not album_id:
            continue
        match action.kind:
            case "rename":
                await _apply_rename(action, album_id, client, state)
            case "add_assets":
                await _apply_add_assets(action, album_id, client, state)
            case "remove_assets":
                await _apply_remove_assets(action, album_id, client, state)
            case "share":
                await _apply_share(action, album_id, client, state)
            case "delete":
                await _apply_delete(action, album_id, client, state)
            case "forget":
                _apply_forget(action, album_id, state, "forget_album")
            case "track_assets":
                state.replace_synced_album_assets(album_id, set(action.asset_ids))
            case "set_description":
                await _apply_set_description(action, album_id, client, state)
            case "set_order":
                await _apply_set_order(action, album_id, client, state)


class Step:
    name = "albums"
    status_msg = "Syncing albums..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.albums

    async def plan(self, ctx: SyncContext, summary: SyncSummary) -> list[AlbumAction]:
        actions = await plan_album_sync(ctx)
        kinds = [a.kind for a in actions]
        summary.albums_created = kinds.count("create")
        summary.albums_renamed = kinds.count("rename")
        summary.albums_deleted = kinds.count("delete")
        summary.assets_added = sum(
            len(a.asset_ids) for a in actions if a.kind == "add_assets"
        )
        summary.assets_removed = sum(
            len(a.asset_ids) for a in actions if a.kind == "remove_assets"
        )
        return actions

    async def apply(self, plan: list[AlbumAction], ctx: SyncContext) -> None:
        await apply_album_sync(plan, ctx.client, ctx.state)
