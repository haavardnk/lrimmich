import asyncio
import random
from collections.abc import Callable

import httpx

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB

CONCURRENCY = 10


def map_path(relative_path: str, immich_library_path: str, strip: str = "") -> str:
    if strip and relative_path.startswith(strip):
        relative_path = relative_path[len(strip) :]
    return immich_library_path + relative_path


async def _build_immich_index(
    immich_library_path: str,
    client: ImmichClient,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    all_folders = await client.get_folder_paths()
    if immich_library_path:
        prefix = immich_library_path.rstrip("/")
        relevant = [f for f in all_folders if f == prefix or f.startswith(prefix + "/")]
    else:
        relevant = all_folders
    index: dict[str, str] = {}
    total = len(relevant)
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0

    async def _fetch(folder: str) -> list[tuple[str, str]]:
        nonlocal done
        async with sem:
            assets = await client.get_folder_assets(folder)
            done += 1
            if on_progress:
                on_progress(done, total)
            return [
                (a.get("originalPath", ""), a["id"])
                for a in assets
                if a.get("originalPath") and not a.get("isTrashed", False)
            ]

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(_fetch(f)) for f in relevant]

    for task in tasks:
        for orig, asset_id in task.result():
            index[orig] = asset_id
    return index


async def resolve_paths(
    relative_paths: set[str],
    immich_library_path: str,
    client: ImmichClient,
    max_cache_age: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    state: StateDB | None = None,
    strip: str = "",
) -> tuple[dict[str, str], set[str]]:
    cached: dict[str, str] = {}
    cache_hits: set[str] = set()
    missing: set[str] = set()
    if state:
        all_cached = state.get_all_cached_paths(max_age=max_cache_age)
        for rp in relative_paths:
            if rp in all_cached:
                cached[rp] = all_cached[rp]
                cache_hits.add(rp)
            else:
                missing.add(rp)
    else:
        missing = relative_paths

    if missing:
        index = await _build_immich_index(immich_library_path, client, on_progress)
        for rp in missing:
            expected = map_path(rp, immich_library_path, strip)
            asset_id = index.get(expected)
            if asset_id:
                cached[rp] = asset_id
    return cached, cache_hits


async def spot_check_cache(
    resolved: dict[str, str],
    immich_library_path: str,
    client: ImmichClient,
    state: StateDB,
    pct: int = 5,
    strip: str = "",
) -> int:
    if not resolved:
        return 0
    sample_size = max(1, len(resolved) * pct // 100)
    sample_keys = random.sample(sorted(resolved), min(sample_size, len(resolved)))
    invalid: list[str] = []
    for rp in sample_keys:
        asset_id = resolved[rp]
        try:
            asset = await client.get_asset(asset_id)
        except httpx.HTTPStatusError:
            invalid.append(rp)
            continue
        if not asset or asset.get("isTrashed", False):
            invalid.append(rp)
            continue
        expected = map_path(rp, immich_library_path, strip)
        if asset.get("originalPath") != expected:
            invalid.append(rp)
    if invalid:
        state.invalidate_cache_entries(invalid)
    return len(invalid)
