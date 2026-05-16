from dataclasses import dataclass

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB


@dataclass
class RatingsResult:
    set: int = 0
    cleared: int = 0


def plan_ratings_sync(
    rated: dict[str, int],
    resolved: dict[str, str],
    state: StateDB,
) -> tuple[dict[str, int], list[str]]:
    desired: dict[str, int] = {
        resolved[rp]: rating for rp, rating in rated.items() if rp in resolved
    }
    previous = state.get_synced_ratings()
    to_set: dict[str, int] = {}
    for asset_id, rating in desired.items():
        if previous.get(asset_id) != rating:
            to_set[asset_id] = rating
    to_clear: list[str] = [aid for aid in previous if aid not in desired]
    return to_set, to_clear


def apply_ratings_sync(
    to_set: dict[str, int],
    to_clear: list[str],
    client: ImmichClient,
    state: StateDB,
) -> RatingsResult:
    by_rating: dict[int, list[str]] = {}
    for asset_id, rating in to_set.items():
        by_rating.setdefault(rating, []).append(asset_id)
    for rating, asset_ids in by_rating.items():
        client.bulk_update_assets(sorted(asset_ids), rating=rating)
    if to_clear:
        client.bulk_update_assets(sorted(to_clear), rating=0)
    total_set = len(to_set)
    total_cleared = len(to_clear)
    if total_set or total_cleared:
        all_desired = dict(state.get_synced_ratings())
        all_desired.update(to_set)
        for aid in to_clear:
            all_desired.pop(aid, None)
        state.replace_synced_ratings(all_desired)
        state.append_audit_log(
            "sync_ratings",
            "ratings",
            payload={"set": total_set, "cleared": total_cleared},
        )
    return RatingsResult(set=total_set, cleared=total_cleared)
