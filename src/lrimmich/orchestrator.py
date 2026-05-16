from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from lrimmich.catalog import (
    read_collections,
    read_flagged_images,
    read_rated_images,
    read_rejected_images,
)
from lrimmich.config import Config
from lrimmich.immich import ImmichClient
from lrimmich.resolver import resolve_paths
from lrimmich.state import StateDB
from lrimmich.sync.albums import (
    AlbumAction,
    apply_album_sync,
    plan_album_sync,
)
from lrimmich.sync.favorites import (
    FavoritesResult,
    apply_favorites_sync,
    plan_favorites_sync,
)
from lrimmich.sync.ratings import (
    RatingsResult,
    apply_ratings_sync,
    plan_ratings_sync,
)
from lrimmich.sync.rejects import (
    RejectsResult,
    apply_rejects_sync,
    plan_rejects_sync,
)


@dataclass
class SyncSummary:
    albums_created: int = 0
    albums_renamed: int = 0
    albums_deleted: int = 0
    assets_added: int = 0
    assets_removed: int = 0
    favorites: FavoritesResult = field(default_factory=FavoritesResult)
    ratings: RatingsResult = field(default_factory=RatingsResult)
    rejects: RejectsResult = field(default_factory=RejectsResult)
    errors: list[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return (
            self.albums_created > 0
            or self.albums_renamed > 0
            or self.albums_deleted > 0
            or self.assets_added > 0
            or self.assets_removed > 0
            or self.favorites.favorited > 0
            or self.favorites.unfavorited > 0
            or self.ratings.updated > 0
            or self.rejects.archived > 0
            or self.rejects.unarchived > 0
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _count_actions(actions: list[AlbumAction]) -> dict[str, int]:
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


def run_sync(
    cfg: Config,
    client: ImmichClient,
    state: StateDB,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    on_status: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> SyncSummary:
    summary = SyncSummary()

    if on_status:
        on_status("Reading catalog...")
    collections = read_collections(cfg.lightroom.catalog, cfg.exclude)
    all_paths: set[str] = set()
    for col in collections:
        all_paths.update(col.relative_paths)

    if on_status:
        on_status(f"Resolving {len(all_paths)} paths...")
    resolved = resolve_paths(
        all_paths,
        cfg.immich.library_path,
        client,
        on_progress=on_progress,
        strip=cfg.lightroom.strip,
    )
    if on_status:
        on_status(f"Resolved {len(resolved)}/{len(all_paths)} assets")
    for rp, asset_id in resolved.items():
        state.upsert_path_cache(rp, asset_id, rp)

    if cfg.sync.albums:
        if on_status:
            on_status("Planning album sync...")
        try:
            album_actions = plan_album_sync(
                collections,
                resolved,
                state,
                client,
                share_with=cfg.immich.share_albums_with,
                safety=cfg.safety,
                force=force,
                no_delete=no_delete,
                skip_empty=cfg.sync.skip_empty,
            )
            counts = _count_actions(album_actions)
            summary.albums_created = counts["created"]
            summary.albums_renamed = counts["renamed"]
            summary.albums_deleted = counts["deleted"]
            summary.assets_added = counts["assets_added"]
            summary.assets_removed = counts["assets_removed"]

            if not dry_run:
                apply_album_sync(album_actions, client, state)
        except Exception as e:
            summary.errors.append(f"albums: {e}")

    if cfg.sync.favorites:
        if on_status:
            on_status("Planning favorites sync...")
        try:
            flagged = read_flagged_images(cfg.lightroom.catalog)
            to_fav, to_unfav = plan_favorites_sync(
                flagged, cfg.favorites.scope, collections, state
            )
            summary.favorites = FavoritesResult(
                favorited=len(to_fav),
                unfavorited=len(to_unfav),
            )
            if not dry_run:
                apply_favorites_sync(to_fav, to_unfav, client, state)
        except Exception as e:
            summary.errors.append(f"favorites: {e}")

    if cfg.sync.ratings:
        if on_status:
            on_status("Syncing ratings...")
        try:
            rated = read_rated_images(cfg.lightroom.catalog)
            plan = plan_ratings_sync(rated, resolved)
            summary.ratings = RatingsResult(updated=len(plan))
            if not dry_run:
                apply_ratings_sync(plan, client, state)
        except Exception as e:
            summary.errors.append(f"ratings: {e}")

    if cfg.sync.rejects:
        if on_status:
            on_status("Syncing rejects...")
        try:
            rejected = read_rejected_images(cfg.lightroom.catalog)
            to_arch, to_unarch = plan_rejects_sync(rejected, resolved)
            summary.rejects = RejectsResult(
                archived=len(to_arch),
                unarchived=len(to_unarch),
            )
            if not dry_run:
                apply_rejects_sync(to_arch, to_unarch, client, state)
        except Exception as e:
            summary.errors.append(f"rejects: {e}")

    return summary
