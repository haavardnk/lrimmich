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
from lrimmich.utils.resolver import resolve_paths

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


CACHE_TTL_SECONDS: int = 7_776_000


async def run_sync(
    cfg: Config,
    client: ImmichClient,
    state: StateDB,
    dry_run: bool = False,
    force: bool = False,
    no_delete: bool = False,
    on_status: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    refresh_cache: bool = False,
) -> SyncSummary:
    summary = SyncSummary()

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
    resolved = await resolve_paths(
        all_paths,
        cfg.immich.library_path,
        client,
        state=state,
        on_progress=on_progress,
        strip=cfg.lightroom.strip,
        max_cache_age=None if refresh_cache else CACHE_TTL_SECONDS,
    )
    if on_status:
        on_status(f"Resolved {len(resolved)}/{len(all_paths)} assets")
    state.upsert_path_cache_bulk([(rp, aid, rp) for rp, aid in resolved.items()])

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

    for step in STEPS:
        if not step.enabled(cfg):
            continue
        logger.debug("step_start", step=step.name)
        if on_status:
            on_status(step.status_msg)
        try:
            plan = await step.plan(ctx, summary)
            if not dry_run:
                await step.apply(plan, ctx)
        except Exception as e:
            logger.exception("step_failed", step=step.name)
            summary.errors.append(f"{step.name}: {e}")

    if not dry_run and not summary.errors:
        state.set_meta("catalog_fingerprint", fingerprint)

    return summary
