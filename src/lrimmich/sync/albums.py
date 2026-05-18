from dataclasses import dataclass, field
from fnmatch import fnmatch

from lrimmich.clients.catalog import LrCollection
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.utils.config import AlbumFilter, AlbumMode, AlbumRule, SafetyConfig


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


def resolve_album_filter(
    collection: LrCollection,
    album_filter: AlbumFilter,
    album_min_rating: int,
    album_rules: list[AlbumRule] | None,
) -> tuple[AlbumFilter, int]:
    for rule in album_rules or []:
        if (rule.id is not None and rule.id == collection.id) or (
            rule.match and fnmatch(collection.full_name, rule.match)
        ):
            return (
                rule.filter or album_filter,
                rule.min_rating if rule.min_rating is not None else album_min_rating,
            )
    return (album_filter, album_min_rating)


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
    filt, min_rat = resolve_album_filter(
        collection, album_filter, album_min_rating, album_rules
    )
    paths = collection.relative_paths
    if filt == "flagged":
        paths = [p for p in paths if p in flagged_paths]
    elif filt == "unflagged":
        paths = [p for p in paths if p not in rejected_paths]
    elif filt == "rejected":
        paths = [p for p in paths if p in rejected_paths]
    if min_rat > 0:
        paths = [p for p in paths if rated_paths.get(p, 0) >= min_rat]
    return [resolved[p] for p in paths if p in resolved]


def plan_album_sync(
    collections: list[LrCollection],
    resolved: dict[str, str],
    state: StateDB,
    client: ImmichClient,
    share_with: list[str] | None = None,
    safety: SafetyConfig | None = None,
    force: bool = False,
    no_delete: bool = False,
    skip_empty: bool = True,
    album_name_format: str = "{path}",
    album_mode: AlbumMode = "managed",
    album_filter: AlbumFilter = "all",
    album_min_rating: int = 0,
    album_rules: list[AlbumRule] | None = None,
    flagged_paths: set[str] | None = None,
    rejected_paths: set[str] | None = None,
    rated_paths: dict[str, int] | None = None,
) -> list[AlbumAction]:
    safety = safety or SafetyConfig()
    share_with = share_with or []
    flagged_paths = flagged_paths or set()
    rejected_paths = rejected_paths or set()
    rated_paths = rated_paths or {}
    actions: list[AlbumAction] = []
    lr_ids = {c.id for c in collections}

    all_albums = {a["id"]: a for a in client.get_albums()} if share_with else {}

    for collection in collections:
        album_name = format_album_name(collection, album_name_format)
        asset_ids = _filtered_asset_ids(
            collection,
            resolved,
            album_filter,
            album_min_rating,
            album_rules,
            flagged_paths,
            rejected_paths,
            rated_paths,
        )
        ownership = state.get_album_ownership(collection.id)

        if skip_empty and not asset_ids:
            if ownership is None:
                continue
            lr_ids.discard(collection.id)
            continue

        if ownership is None:
            actions.append(
                AlbumAction(
                    kind="create",
                    lr_collection_id=collection.id,
                    album_name=album_name,
                    asset_ids=asset_ids,
                )
            )
            if share_with:
                actions.append(
                    AlbumAction(
                        kind="share",
                        lr_collection_id=collection.id,
                        album_name=album_name,
                        user_ids=list(share_with),
                    )
                )
            continue

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

        album_data = client.get_album(immich_album_id)
        current_ids = {a["id"] for a in album_data.get("assets", [])}
        desired_ids = set(asset_ids)

        to_add = sorted(desired_ids - current_ids)

        if album_mode == "hybrid":
            tracked_ids = state.get_synced_album_assets(immich_album_id)
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
            if pct > safety.remove_percent_limit and not force:
                raise RemoveLimitExceeded(
                    album_name,
                    len(to_remove),
                    pct,
                    safety.remove_percent_limit,
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

        if share_with:
            album_summary = all_albums.get(immich_album_id, {})
            shared_ids = {u["user"]["id"] for u in album_summary.get("albumUsers", [])}
            unshared = [uid for uid in share_with if uid not in shared_ids]
            if unshared:
                actions.append(
                    AlbumAction(
                        kind="share",
                        lr_collection_id=collection.id,
                        immich_album_id=immich_album_id,
                        album_name=album_name,
                        user_ids=unshared,
                    )
                )

    owned = state.get_all_owned_albums()
    to_delete = [o for o in owned if o["lr_collection_id"] not in lr_ids]

    if to_delete and not no_delete and not safety.disable_deletes:
        if len(to_delete) > safety.delete_threshold and not force:
            raise DeleteThresholdExceeded(len(to_delete), safety.delete_threshold)
        for o in to_delete:
            actions.append(
                AlbumAction(
                    kind="delete",
                    lr_collection_id=o["lr_collection_id"],
                    immich_album_id=o["immich_album_id"],
                    album_name=o["last_name"],
                )
            )

    return actions


def _apply_create(action: AlbumAction, client: ImmichClient, state: StateDB) -> str:
    result = client.create_album(action.album_name, action.asset_ids)
    album_id: str = result["id"]
    state.upsert_album_ownership(action.lr_collection_id, album_id, action.album_name)
    state.replace_synced_album_assets(album_id, set(action.asset_ids))
    state.append_audit_log(
        "create_album",
        "album",
        album_id,
        {"name": action.album_name, "assets": len(action.asset_ids)},
    )
    return album_id


def _apply_rename(action: AlbumAction, client: ImmichClient, state: StateDB) -> None:
    if not action.immich_album_id:
        return
    client.update_album(action.immich_album_id, albumName=action.album_name)
    state.upsert_album_ownership(
        action.lr_collection_id, action.immich_album_id, action.album_name
    )
    state.append_audit_log(
        "rename_album",
        "album",
        action.immich_album_id,
        {"old": action.old_name, "new": action.album_name},
    )


def _apply_add_assets(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id:
        return
    client.add_album_assets(action.immich_album_id, action.asset_ids)
    state.add_synced_album_assets(action.immich_album_id, set(action.asset_ids))
    state.append_audit_log(
        "add_assets",
        "album",
        action.immich_album_id,
        {"count": len(action.asset_ids)},
    )


def _apply_remove_assets(
    action: AlbumAction, client: ImmichClient, state: StateDB
) -> None:
    if not action.immich_album_id:
        return
    client.remove_album_assets(action.immich_album_id, action.asset_ids)
    state.remove_synced_album_assets(action.immich_album_id, set(action.asset_ids))
    state.append_audit_log(
        "remove_assets",
        "album",
        action.immich_album_id,
        {"count": len(action.asset_ids)},
    )


def _apply_share(
    action: AlbumAction,
    client: ImmichClient,
    state: StateDB,
    created: dict[int, str],
) -> None:
    album_id = action.immich_album_id or created.get(action.lr_collection_id)
    if not album_id:
        return
    client.add_album_users(album_id, action.user_ids)
    state.append_audit_log("share_album", "album", album_id, {"users": action.user_ids})


def _apply_delete(action: AlbumAction, client: ImmichClient, state: StateDB) -> None:
    if not action.immich_album_id:
        return
    client.delete_album(action.immich_album_id)
    state.remove_album_ownership(action.lr_collection_id)
    state.clear_synced_album_assets(action.immich_album_id)
    state.append_audit_log(
        "delete_album", "album", action.immich_album_id, {"name": action.album_name}
    )


def _apply_track_assets(action: AlbumAction, state: StateDB) -> None:
    if not action.immich_album_id:
        return
    state.replace_synced_album_assets(action.immich_album_id, set(action.asset_ids))


def apply_album_sync(
    actions: list[AlbumAction],
    client: ImmichClient,
    state: StateDB,
) -> None:
    created: dict[int, str] = {}

    for action in actions:
        match action.kind:
            case "create":
                created[action.lr_collection_id] = _apply_create(action, client, state)
            case "rename":
                _apply_rename(action, client, state)
            case "add_assets":
                _apply_add_assets(action, client, state)
            case "remove_assets":
                _apply_remove_assets(action, client, state)
            case "share":
                _apply_share(action, client, state, created)
            case "delete":
                _apply_delete(action, client, state)
            case "track_assets":
                _apply_track_assets(action, state)
