import asyncio
from collections.abc import Callable
from typing import Any

import structlog

from lrimmich.clients.catalog import read_catalog_fingerprint, read_collections
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
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
from lrimmich.utils.config import Config
from lrimmich.utils.resolver import resolve_paths, spot_check_cache

logger = structlog.get_logger(__name__)

SERIAL_STEPS: list[SyncStep[Any]] = [
    albums.Step(),
    covers.Step(),
]

PARALLEL_STEPS: list[SyncStep[Any]] = [
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
    dry_run: bool,
) -> None:
    logger.debug("step_start", step=step.name)
    try:
        plan = await step.plan(ctx, summary)
        if not dry_run:
            await step.apply(plan, ctx)
    except Exception as e:
        logger.exception("step_failed", step=step.name)
        summary.errors.append(f"{step.name}: {e}")


async def run_sync(
    cfg: Config,
    client: ImmichClient,
    state: StateDB,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    on_confirm: Callable[[str, str], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_status: Callable[[str], None] | None = None,
    refresh_cache: bool = False,
) -> SyncSummary:
    summary = SyncSummary()
    cache_ttl = cfg.cache.ttl_days * DAY_SECONDS

    if refresh_cache:
        state.clear_path_cache()

    if on_status:
        on_status("Reading catalog...")
    collections = read_collections(cfg.lightroom.catalog, cfg.exclude)

    fingerprint = read_catalog_fingerprint(cfg.lightroom.catalog)
    last_fingerprint = state.get_meta("catalog_fingerprint")
    if (
        not force
        and not refresh_cache
        and last_fingerprint
        and fingerprint == last_fingerprint
    ):
        logger.debug("catalog_unchanged", fingerprint=fingerprint)
        return summary

    all_paths: set[str] = set()
    for col in collections:
        all_paths.update(col.relative_paths)

    if on_status:
        on_status(f"Resolving {len(all_paths)} paths...")
    resolved, cache_hits = await resolve_paths(
        all_paths,
        cfg.immich.library_path,
        client,
        max_cache_age=None if refresh_cache else cache_ttl,
        on_progress=on_progress,
        state=state,
        strip=cfg.lightroom.strip,
    )
    if on_status:
        on_status(f"Resolved {len(resolved)}/{len(all_paths)} assets")
    state.upsert_path_cache_bulk([(rp, aid, rp) for rp, aid in resolved.items()])

    if cache_hits and cfg.cache.spot_check_pct > 0:
        cached_subset = {rp: resolved[rp] for rp in cache_hits if rp in resolved}
        invalidated = await spot_check_cache(
            cached_subset,
            cfg.immich.library_path,
            client,
            state,
            pct=cfg.cache.spot_check_pct,
            strip=cfg.lightroom.strip,
        )
        if invalidated:
            logger.info("cache_spot_check", invalidated=invalidated)

    state.evict_stale_cache(cache_ttl * 2)

    ctx = SyncContext(
        cfg=cfg,
        client=client,
        state=state,
        collections=collections,
        resolved=resolved,
        dry_run=dry_run,
        force=force,
        no_delete=no_delete,
    )

    for step in SERIAL_STEPS:
        if not step.enabled(cfg):
            continue
        logger.debug("step_start", step=step.name)
        if on_status:
            on_status(step.status_msg)
        try:
            plan = await step.plan(ctx, summary)
            if not dry_run:
                if on_confirm and not on_confirm(step.name, step.status_msg):
                    continue
                await step.apply(plan, ctx)
        except Exception as e:
            logger.exception("step_failed", step=step.name)
            summary.errors.append(f"{step.name}: {e}")

    enabled_parallel = [s for s in PARALLEL_STEPS if s.enabled(cfg)]
    if enabled_parallel:
        if on_confirm:
            for step in enabled_parallel:
                logger.debug("step_start", step=step.name)
                if on_status:
                    on_status(step.status_msg)
                try:
                    plan = await step.plan(ctx, summary)
                    if not dry_run:
                        if not on_confirm(step.name, step.status_msg):
                            continue
                        await step.apply(plan, ctx)
                except Exception as e:
                    logger.exception("step_failed", step=step.name)
                    summary.errors.append(f"{step.name}: {e}")
        else:
            if on_status:
                on_status("Syncing metadata...")
            await asyncio.gather(*(
                _run_step(step, ctx, summary, dry_run)
                for step in enabled_parallel
            ))

    if not dry_run and not summary.errors:
        state.set_meta("catalog_fingerprint", fingerprint)

    return summary
