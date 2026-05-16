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
) -> tuple[list[str], list[str]]:
    to_archive: list[str] = []
    to_unarchive: list[str] = []
    for rp, asset_id in resolved.items():
        if rp in rejected:
            to_archive.append(asset_id)
        else:
            to_unarchive.append(asset_id)
    return sorted(to_archive), sorted(to_unarchive)


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
        state.append_audit_log(
            "sync_rejects",
            "rejects",
            payload={
                "archived": result.archived,
                "unarchived": result.unarchived,
            },
        )
    return result
