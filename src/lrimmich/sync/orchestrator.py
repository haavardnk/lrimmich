import sqlite3
import time
from collections.abc import Callable
from hashlib import sha256
from typing import Any

import httpx
import structlog

from lrimmich.clients.catalog import (
    read_catalog_fingerprint,
    read_collections,
    read_image_paths,
)
from lrimmich.clients.immich import ImmichClient, ImmichUnreachableError
from lrimmich.clients.state import StateDB, state_path_for_catalog
from lrimmich.sync import (
    albums,
    captions,
    color_labels,
    covers,
    favorites,
    keywords,
    ratings,
    rejects,
    stacks,
)
from lrimmich.sync.context import SyncContext, SyncStep
from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.adopt import apply_adopt, find_adopt_candidates
from lrimmich.utils.config import CatalogConfig, Config
from lrimmich.utils.resolver import resolve_paths, spot_check_cache

logger = structlog.get_logger(__name__)

STEPS: list[SyncStep[Any]] = [
    albums.Step(),
    covers.Step(),
    favorites.Step(),
    ratings.Step(),
    rejects.Step(),
    color_labels.Step(),
    keywords.Step(),
    captions.Step(),
    stacks.Step(),
]

DAY_SECONDS: int = 86_400


async def _run_step(
    step: SyncStep[Any],
    ctx: SyncContext,
    summary: SyncSummary,
    on_confirm: Callable[[str, SyncSummary], bool] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> None:
    logger.debug("step_start", step=step.name)
    if on_status:
        on_status(step.status_msg)
    planned = SyncSummary()
    try:
        plan = await step.plan(ctx, planned)
        if (
            on_confirm
            and not ctx.dry_run
            and planned.has_drift
            and not on_confirm(step.name, planned)
        ):
            return
        if not ctx.dry_run:
            await step.apply(plan, ctx)
    except* ImmichUnreachableError:
        raise
    except* (httpx.HTTPError, sqlite3.Error, albums.AlbumSyncError) as eg:
        logger.exception("step_failed", step=step.name)
        summary.errors.extend(f"{step.name}: {e}" for e in eg.exceptions)
    summary.merge(planned)


async def run_sync(
    cfg: Config,
    catalog: CatalogConfig,
    client: ImmichClient,
    state: StateDB,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    adopt_existing: bool = False,
    on_confirm: Callable[[str, SyncSummary], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    refresh_cache: bool = False,
) -> SyncSummary:
    summary = SyncSummary()
    cache_ttl = cfg.cache.ttl_days * DAY_SECONDS

    if refresh_cache:
        state.clear_path_cache()

    if on_status:
        on_status(f"Reading catalog {catalog.catalog.name}...")
    collections = read_collections(catalog.catalog, catalog)

    fingerprint = read_catalog_fingerprint(catalog.catalog)
    config_hash = sha256(cfg.model_dump_json().encode()).hexdigest()[:16]
    combined_fingerprint = f"{fingerprint}:{config_hash}"
    last_fingerprint = state.get_meta("catalog_fingerprint")
    retry_at = int(state.get_meta("unresolved_retry_at") or 0)
    unchanged = (
        not force
        and not dry_run
        and not refresh_cache
        and combined_fingerprint == last_fingerprint
    )
    if unchanged and (not retry_at or time.time() < retry_at):
        logger.debug("catalog_unchanged", fingerprint=combined_fingerprint)
        summary.skipped_unchanged = True
        return summary

    all_paths: set[str] = set()
    for col in collections:
        all_paths.update(col.relative_paths)
    if cfg.sync.scope == "all":
        all_paths.update(read_image_paths(catalog.catalog))

    if cfg.cache.spot_check_pct > 0 and not refresh_cache:
        cached = state.get_all_cached_paths(max_age=cache_ttl)
        invalidated = await spot_check_cache(
            {rp: aid for rp, aid in cached.items() if rp in all_paths},
            cfg.immich.library_paths,
            client,
            state,
            pct=cfg.cache.spot_check_pct,
            strip=catalog.strip,
        )
        if invalidated:
            logger.info("cache_spot_check", invalidated=invalidated)

    if on_status:
        on_status(f"Resolving {len(all_paths)} paths...")
    resolved, cache_hits = await resolve_paths(
        all_paths,
        cfg.immich.library_paths,
        client,
        max_cache_age=None if refresh_cache else cache_ttl,
        on_progress=on_progress,
        state=state,
        strip=catalog.strip,
        miss_max_age=cfg.cache.miss_ttl_minutes * 60 or None,
    )
    if on_status:
        on_status(f"Resolved {len(resolved)}/{len(all_paths)} assets")
    summary.unresolved = len(all_paths) - len(resolved)
    state.upsert_path_cache_bulk(
        {rp: aid for rp, aid in resolved.items() if rp not in cache_hits}
    )

    state.evict_stale_cache(cache_ttl * 2)

    unresolved_digest = sha256(
        "\n".join(sorted(all_paths - resolved.keys())).encode()
    ).hexdigest()[:16]
    next_retry_at = int(time.time()) + cfg.cache.miss_ttl_minutes * 60
    if unchanged and unresolved_digest == state.get_meta("unresolved_digest"):
        logger.debug("unresolved_unchanged", unresolved=summary.unresolved)
        state.set_meta("unresolved_retry_at", str(next_retry_at))
        summary.skipped_unchanged = True
        return summary

    if cfg.sync.albums:
        unowned_cols = [
            c for c in collections if state.get_album_ownership(c.id) is None
        ]
        if unowned_cols:
            candidates = await find_adopt_candidates(
                unowned_cols, client, state, cfg.sync.album_name_format
            )
            unowned = [c for c in candidates if not c.conflict]
            if unowned:
                if adopt_existing:
                    if not dry_run:
                        apply_adopt(unowned, state)
                    logger.info("adopted_existing", count=len(unowned))
                else:
                    names = ", ".join(sorted({c.collection_name for c in unowned})[:5])
                    more = f" (+{len(unowned) - 5} more)" if len(unowned) > 5 else ""
                    summary.errors.append(
                        f"albums: {len(unowned)} Immich album(s) match "
                        f"collection names but are not tracked: {names}{more}. "
                        "Skipped the rest of the sync for this catalog. "
                        "Run with --adopt-existing to claim them, "
                        "or --adopt-existing --dry-run to review first."
                    )
                    return summary

    ctx = SyncContext(
        cfg=cfg,
        catalog=catalog,
        client=client,
        state=state,
        collections=collections,
        resolved=resolved,
        dry_run=dry_run,
        force=force,
        no_delete=no_delete,
    )

    for step in STEPS:
        if step.enabled(cfg):
            await _run_step(step, ctx, summary, on_confirm, on_status)

    if not dry_run and not summary.errors:
        state.set_meta("catalog_fingerprint", combined_fingerprint)
        state.set_meta("unresolved_digest", unresolved_digest)
        state.set_meta(
            "unresolved_retry_at", str(next_retry_at) if summary.unresolved else ""
        )

    return summary


async def run_multi_sync(
    cfg: Config,
    client: ImmichClient,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    adopt_existing: bool = False,
    on_confirm: Callable[[str, SyncSummary], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    refresh_cache: bool = False,
) -> SyncSummary:
    combined = SyncSummary()
    skipped = 0
    for catalog in cfg.catalogs:
        state_db = state_path_for_catalog(catalog.key)
        state = StateDB(state_db)
        unreachable = False
        try:
            summary = await run_sync(
                cfg,
                catalog,
                client,
                state,
                dry_run=dry_run,
                force=force,
                no_delete=no_delete,
                adopt_existing=adopt_existing,
                on_confirm=on_confirm,
                on_progress=on_progress,
                on_status=on_status,
                refresh_cache=refresh_cache,
            )
        except* ImmichUnreachableError as eg:
            logger.error("immich_unreachable", error=str(eg.exceptions[0]))
            summary = SyncSummary(errors=[str(eg.exceptions[0])])
            unreachable = True
        except* (httpx.HTTPError, sqlite3.Error) as eg:
            logger.exception("catalog_failed", catalog=catalog.catalog.name)
            summary = SyncSummary(
                errors=[f"{catalog.catalog.name}: {e}" for e in eg.exceptions]
            )
        finally:
            state.close()
        combined.merge(summary)
        if unreachable:
            break
        if summary.skipped_unchanged:
            skipped += 1
    combined.skipped_unchanged = bool(cfg.catalogs) and skipped == len(cfg.catalogs)
    return combined
