from dataclasses import dataclass

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB


@dataclass
class RatingsResult:
    updated: int = 0


def plan_ratings_sync(
    rated: dict[str, int],
    resolved: dict[str, str],
) -> dict[str, int]:
    return {resolved[rp]: rating for rp, rating in rated.items() if rp in resolved}


def apply_ratings_sync(
    plan: dict[str, int],
    client: ImmichClient,
    state: StateDB,
) -> RatingsResult:
    by_rating: dict[int, list[str]] = {}
    for asset_id, rating in plan.items():
        by_rating.setdefault(rating, []).append(asset_id)
    total = 0
    for rating, asset_ids in by_rating.items():
        client.bulk_update_assets(sorted(asset_ids), rating=rating)
        total += len(asset_ids)
    if total:
        state.append_audit_log(
            "sync_ratings",
            "ratings",
            payload={"updated": total},
        )
    return RatingsResult(updated=total)
