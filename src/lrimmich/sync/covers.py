from dataclasses import dataclass

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB


@dataclass
class CoversResult:
    set: int = 0
    cleared: int = 0


def plan_covers_sync(
    cover_paths: dict[int, str],
    resolved: dict[str, str],
    state: StateDB,
) -> tuple[dict[str, str], list[str]]:
    desired: dict[str, str] = {}
    for lr_id, rel_path in cover_paths.items():
        if rel_path not in resolved:
            continue
        ownership = state.get_album_ownership(lr_id)
        if ownership is None:
            continue
        immich_album_id: str = ownership["immich_album_id"]
        desired[immich_album_id] = resolved[rel_path]
    previous = state.get_synced_covers()
    to_set: dict[str, str] = {
        aid: asset for aid, asset in desired.items() if previous.get(aid) != asset
    }
    to_clear: list[str] = [aid for aid in previous if aid not in desired]
    return to_set, to_clear


def apply_covers_sync(
    to_set: dict[str, str],
    to_clear: list[str],
    client: ImmichClient,
    state: StateDB,
) -> CoversResult:
    for album_id, asset_id in sorted(to_set.items()):
        client.update_album(album_id, albumThumbnailAssetId=asset_id)
    for album_id in sorted(to_clear):
        client.update_album(album_id, albumThumbnailAssetId=None)
    total_set = len(to_set)
    total_cleared = len(to_clear)
    if total_set or total_cleared:
        all_desired = dict(state.get_synced_covers())
        all_desired.update(to_set)
        for aid in to_clear:
            all_desired.pop(aid, None)
        state.replace_synced_covers(all_desired)
        state.append_audit_log(
            "sync_covers",
            "albums",
            payload={"set": total_set, "cleared": total_cleared},
        )
    return CoversResult(set=total_set, cleared=total_cleared)
