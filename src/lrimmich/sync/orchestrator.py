from collections.abc import Callable

from lrimmich.clients.catalog import (
    read_collection_covers,
    read_collections,
    read_color_labels,
    read_flagged_images,
    read_keywords,
    read_rated_images,
    read_rejected_images,
)
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync.albums import (
    apply_album_sync,
    plan_album_sync,
)
from lrimmich.sync.color_labels import (
    COLOR_TAG_PREFIX,
    VALID_COLORS,
    ColorLabelsResult,
    apply_color_labels_sync,
    plan_color_labels_sync,
)
from lrimmich.sync.covers import (
    CoversResult,
    apply_covers_sync,
    plan_covers_sync,
)
from lrimmich.sync.favorites import (
    FavoritesResult,
    apply_favorites_sync,
    plan_favorites_sync,
)
from lrimmich.sync.keywords import (
    KEYWORD_TAG_PREFIX,
    KeywordsResult,
    apply_keywords_sync,
    plan_keywords_sync,
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
from lrimmich.sync.summary import SyncSummary, count_album_actions
from lrimmich.sync.tags import ensure_tags
from lrimmich.utils.config import Config
from lrimmich.utils.resolver import resolve_paths


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
        state=state,
        on_progress=on_progress,
        strip=cfg.lightroom.strip,
    )
    if on_status:
        on_status(f"Resolved {len(resolved)}/{len(all_paths)} assets")
    state.upsert_path_cache_bulk([(rp, aid, rp) for rp, aid in resolved.items()])

    flagged: set[str] | None = None
    rejected: set[str] | None = None
    rated: dict[str, int] | None = None

    if cfg.sync.albums:
        if on_status:
            on_status("Syncing albums...")
        try:
            needs_flagged = cfg.sync.album_filter == "flagged" or any(
                r.filter == "flagged" for r in cfg.album_rules
            )
            needs_rejected = cfg.sync.album_filter in ("unflagged", "rejected") or any(
                r.filter in ("unflagged", "rejected") for r in cfg.album_rules
            )
            needs_rated = cfg.sync.album_min_rating > 0 or any(
                (r.min_rating or 0) > 0 for r in cfg.album_rules
            )
            if needs_flagged:
                flagged = read_flagged_images(cfg.lightroom.catalog)
            if needs_rejected:
                rejected = read_rejected_images(cfg.lightroom.catalog)
            if needs_rated:
                rated = read_rated_images(cfg.lightroom.catalog)
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
                album_name_format=cfg.sync.album_name_format,
                album_mode=cfg.sync.album_mode,
                album_filter=cfg.sync.album_filter,
                album_min_rating=cfg.sync.album_min_rating,
                album_rules=cfg.album_rules,
                flagged_paths=flagged,
                rejected_paths=rejected,
                rated_paths=rated,
            )
            counts = count_album_actions(album_actions)
            summary.albums_created = counts["created"]
            summary.albums_renamed = counts["renamed"]
            summary.albums_deleted = counts["deleted"]
            summary.assets_added = counts["assets_added"]
            summary.assets_removed = counts["assets_removed"]

            if not dry_run:
                apply_album_sync(album_actions, client, state)
        except Exception as e:
            summary.errors.append(f"albums: {e}")

        if on_status:
            on_status("Syncing album covers...")
        try:
            cover_paths = read_collection_covers(cfg.lightroom.catalog)
            to_set, to_clear = plan_covers_sync(cover_paths, resolved, state)
            summary.covers = CoversResult(set=len(to_set), cleared=len(to_clear))
            if not dry_run:
                apply_covers_sync(to_set, to_clear, client, state)
        except Exception as e:
            summary.errors.append(f"covers: {e}")

    if cfg.sync.favorites:
        if on_status:
            on_status("Syncing favorites...")
        try:
            if flagged is None:
                flagged = read_flagged_images(cfg.lightroom.catalog)
            to_fav, to_unfav = plan_favorites_sync(
                flagged, cfg.sync.scope, collections, state
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
            if rated is None:
                rated = read_rated_images(cfg.lightroom.catalog)
            to_set, to_clear = plan_ratings_sync(rated, resolved, state)
            summary.ratings = RatingsResult(set=len(to_set), cleared=len(to_clear))
            if not dry_run:
                apply_ratings_sync(to_set, to_clear, client, state)
        except Exception as e:
            summary.errors.append(f"ratings: {e}")

    if cfg.sync.rejects:
        if on_status:
            on_status("Syncing rejects...")
        try:
            if rejected is None:
                rejected = read_rejected_images(cfg.lightroom.catalog)
            to_arch, to_unarch = plan_rejects_sync(rejected, resolved, state)
            summary.rejects = RejectsResult(
                archived=len(to_arch),
                unarchived=len(to_unarch),
            )
            if not dry_run:
                apply_rejects_sync(to_arch, to_unarch, client, state)
        except Exception as e:
            summary.errors.append(f"rejects: {e}")

    if cfg.sync.tags:
        existing_tags = client.get_tags()

        if on_status:
            on_status("Syncing color labels...")
        try:
            labels = read_color_labels(cfg.lightroom.catalog)
            tag_map = ensure_tags(
                client,
                existing_tags,
                {c.lower() for c in VALID_COLORS},
                COLOR_TAG_PREFIX,
                create=not dry_run,
            )
            actions = plan_color_labels_sync(labels, resolved, tag_map, state)
            desired = {
                resolved[rp]: color.lower()
                for rp, color in labels.items()
                if rp in resolved and color.lower() in tag_map
            }
            summary.color_labels = ColorLabelsResult(
                tagged=sum(len(a.asset_ids) for a in actions if a.kind == "tag"),
                untagged=sum(len(a.asset_ids) for a in actions if a.kind == "untag"),
            )
            if not dry_run:
                apply_color_labels_sync(actions, desired, client, state)
        except Exception as e:
            summary.errors.append(f"color_labels: {e}")

        if on_status:
            on_status("Syncing keywords...")
        try:
            kw_data = read_keywords(cfg.lightroom.catalog)
            needed_kws: set[str] = set()
            for kws in kw_data.values():
                needed_kws.update(kws)
            kw_tag_map = ensure_tags(
                client,
                existing_tags,
                needed_kws,
                KEYWORD_TAG_PREFIX,
                create=not dry_run,
            )
            kw_actions = plan_keywords_sync(kw_data, resolved, kw_tag_map, state)
            kw_desired: dict[str, list[str]] = {}
            for rp, kws in kw_data.items():
                if rp in resolved:
                    valid = sorted(k for k in kws if k in kw_tag_map)
                    if valid:
                        kw_desired[resolved[rp]] = valid
            summary.keywords = KeywordsResult(
                tagged=sum(len(a.asset_ids) for a in kw_actions if a.kind == "tag"),
                untagged=sum(len(a.asset_ids) for a in kw_actions if a.kind == "untag"),
            )
            if not dry_run:
                apply_keywords_sync(kw_actions, kw_desired, client, state)
        except Exception as e:
            summary.errors.append(f"keywords: {e}")

    return summary
