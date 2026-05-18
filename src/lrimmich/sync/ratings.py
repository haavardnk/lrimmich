from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.context import SyncContext
from lrimmich.sync.summary import RatingsResult, SyncSummary
from lrimmich.utils.config import Config

RatingsPlan = tuple[dict[str, int], list[str]]


def plan_ratings_sync(
    rated: dict[str, int],
    resolved: dict[str, str],
    state: StateDB,
) -> tuple[dict[str, int], list[str]]:
    desired: dict[str, int] = {
        resolved[rp]: rating for rp, rating in rated.items() if rp in resolved
    }
    previous = state.get_synced_ratings()
    to_set = {aid: r for aid, r in desired.items() if previous.get(aid) != r}
    to_clear = [aid for aid in previous if aid not in desired]
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
    if to_set or to_clear:
        snapshot = dict(state.get_synced_ratings())
        snapshot.update(to_set)
        for aid in to_clear:
            snapshot.pop(aid, None)
        state.replace_synced_ratings(snapshot)
        state.append_audit_log(
            "sync_ratings",
            "ratings",
            payload={"set": len(to_set), "cleared": len(to_clear)},
        )
    return RatingsResult(set=len(to_set), cleared=len(to_clear))


class Step:
    name = "ratings"
    status_msg = "Syncing ratings..."

    def enabled(self, cfg: Config) -> bool:
        return cfg.sync.ratings

    def plan(self, ctx: SyncContext, summary: SyncSummary) -> RatingsPlan:
        to_set, to_clear = plan_ratings_sync(ctx.get_rated(), ctx.resolved, ctx.state)
        summary.ratings = RatingsResult(set=len(to_set), cleared=len(to_clear))
        return to_set, to_clear

    def apply(self, plan: RatingsPlan, ctx: SyncContext) -> None:
        apply_ratings_sync(plan[0], plan[1], ctx.client, ctx.state)
