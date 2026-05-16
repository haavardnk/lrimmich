from dataclasses import dataclass, field

from lrimmich.catalog import LrCollection
from lrimmich.config import SafetyConfig
from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB


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
) -> list[AlbumAction]:
    safety = safety or SafetyConfig()
    share_with = share_with or []
    actions: list[AlbumAction] = []
    lr_ids = {c.id for c in collections}

    for collection in collections:
        asset_ids = [resolved[rp] for rp in collection.relative_paths if rp in resolved]
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
                    album_name=collection.full_name,
                    asset_ids=asset_ids,
                )
            )
            if share_with:
                actions.append(
                    AlbumAction(
                        kind="share",
                        lr_collection_id=collection.id,
                        album_name=collection.full_name,
                        user_ids=list(share_with),
                    )
                )
            continue

        immich_album_id = ownership["immich_album_id"]

        if ownership["last_name"] != collection.full_name:
            actions.append(
                AlbumAction(
                    kind="rename",
                    lr_collection_id=collection.id,
                    immich_album_id=immich_album_id,
                    album_name=collection.full_name,
                    old_name=ownership["last_name"],
                )
            )

        album_data = client.get_album(immich_album_id)
        current_ids = {a["id"] for a in album_data.get("assets", [])}
        desired_ids = set(asset_ids)

        to_add = sorted(desired_ids - current_ids)
        to_remove = sorted(current_ids - desired_ids)

        if to_add:
            actions.append(
                AlbumAction(
                    kind="add_assets",
                    lr_collection_id=collection.id,
                    immich_album_id=immich_album_id,
                    album_name=collection.full_name,
                    asset_ids=to_add,
                )
            )

        if to_remove:
            total = len(current_ids)
            pct = len(to_remove) * 100 // total if total > 0 else 0
            if pct > safety.remove_percent_limit and not force:
                raise RemoveLimitExceeded(
                    collection.full_name,
                    len(to_remove),
                    pct,
                    safety.remove_percent_limit,
                )
            actions.append(
                AlbumAction(
                    kind="remove_assets",
                    lr_collection_id=collection.id,
                    immich_album_id=immich_album_id,
                    album_name=collection.full_name,
                    asset_ids=to_remove,
                )
            )

        if share_with:
            shared_ids = {u["user"]["id"] for u in album_data.get("albumUsers", [])}
            unshared = [uid for uid in share_with if uid not in shared_ids]
            if unshared:
                actions.append(
                    AlbumAction(
                        kind="share",
                        lr_collection_id=collection.id,
                        immich_album_id=immich_album_id,
                        album_name=collection.full_name,
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


def apply_album_sync(
    actions: list[AlbumAction],
    client: ImmichClient,
    state: StateDB,
) -> None:
    created: dict[int, str] = {}

    for action in actions:
        match action.kind:
            case "create":
                result = client.create_album(action.album_name, action.asset_ids)
                album_id = result["id"]
                created[action.lr_collection_id] = album_id
                state.upsert_album_ownership(
                    action.lr_collection_id, album_id, action.album_name
                )
                state.append_audit_log(
                    "create_album",
                    "album",
                    album_id,
                    {"name": action.album_name, "assets": len(action.asset_ids)},
                )

            case "rename":
                if action.immich_album_id:
                    client.update_album(
                        action.immich_album_id, albumName=action.album_name
                    )
                    state.upsert_album_ownership(
                        action.lr_collection_id,
                        action.immich_album_id,
                        action.album_name,
                    )
                    state.append_audit_log(
                        "rename_album",
                        "album",
                        action.immich_album_id,
                        {"old": action.old_name, "new": action.album_name},
                    )

            case "add_assets":
                if action.immich_album_id:
                    client.add_album_assets(action.immich_album_id, action.asset_ids)
                    state.append_audit_log(
                        "add_assets",
                        "album",
                        action.immich_album_id,
                        {"count": len(action.asset_ids)},
                    )

            case "remove_assets":
                if action.immich_album_id:
                    client.remove_album_assets(action.immich_album_id, action.asset_ids)
                    state.append_audit_log(
                        "remove_assets",
                        "album",
                        action.immich_album_id,
                        {"count": len(action.asset_ids)},
                    )

            case "share":
                album_id = action.immich_album_id or created.get(
                    action.lr_collection_id
                )
                if album_id:
                    client.add_album_users(album_id, action.user_ids)
                    state.append_audit_log(
                        "share_album",
                        "album",
                        album_id,
                        {"users": action.user_ids},
                    )

            case "delete":
                if action.immich_album_id:
                    client.delete_album(action.immich_album_id)
                    state.remove_album_ownership(action.lr_collection_id)
                    state.append_audit_log(
                        "delete_album",
                        "album",
                        action.immich_album_id,
                        {"name": action.album_name},
                    )
