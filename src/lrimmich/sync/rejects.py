from dataclasses import dataclass

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB


@dataclass
class RejectsResult:
    archived: int = 0
    unarchived: int = 0


def plan_rejects_sync(
    rejected: set[str],
    resolved: dict[str, str],
    state: StateDB,
) -> tuple[list[str], list[str]]:
    desired_archive: set[str] = set()
    desired_unarchive: set[str] = set()
    for rp, asset_id in resolved.items():
        if rp in rejected:
            desired_archive.add(asset_id)
        else:
            desired_unarchive.add(asset_id)
    previous = state.get_synced_rejects()
    to_archive = sorted(desired_archive - previous)
    to_unarchive = sorted(desired_unarchive & previous)
    return to_archive, to_unarchive


def apply_rejects_sync(
    to_archive: list[str],
    to_unarchive: list[str],
    client: ImmichClient,
    state: StateDB,
) -> RejectsResult:
    if to_archive:
        client.bulk_update_assets(to_archive, isArchived=True)
    if to_unarchive:
        client.bulk_update_assets(to_unarchive, isArchived=False)
    result = RejectsResult(
        archived=len(to_archive),
        unarchived=len(to_unarchive),
    )
    if to_archive or to_unarchive:
        previous = state.get_synced_rejects()
        updated = (previous | set(to_archive)) - set(to_unarchive)
        state.replace_synced_rejects(updated)
        state.append_audit_log(
            "sync_rejects",
            "rejects",
            payload={
                "archived": result.archived,
                "unarchived": result.unarchived,
            },
        )
    return result
