from collections.abc import Callable
from typing import Any

from lrimmich.clients.catalog import read_collections
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.sync import (
    albums,
    color_labels,
    covers,
    favorites,
    keywords,
    ratings,
    rejects,
)
from lrimmich.sync.context import SyncContext, SyncStep
from lrimmich.sync.summary import SyncSummary
from lrimmich.utils.config import Config
from lrimmich.utils.resolver import resolve_paths

STEPS: list[SyncStep[Any]] = [
    albums.Step(),
    covers.Step(),
    favorites.Step(),
    ratings.Step(),
    rejects.Step(),
    color_labels.Step(),
    keywords.Step(),
]


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
        if on_status:
            on_status(step.status_msg)
        try:
            plan = step.plan(ctx, summary)
            if not dry_run:
                step.apply(plan, ctx)
        except Exception as e:
            summary.errors.append(f"{step.name}: {e}")

    return summary
