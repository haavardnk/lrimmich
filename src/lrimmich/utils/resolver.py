import asyncio
from collections.abc import Callable

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
    state: StateDB | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    strip: str = "",
    max_cache_age: int | None = None,
) -> dict[str, str]:
    cached: dict[str, str] = {}
    missing: set[str] = set()
    if state:
        all_cached = state.get_all_cached_paths(max_age=max_cache_age)
        for rp in relative_paths:
            if rp in all_cached:
                cached[rp] = all_cached[rp]
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
    return cached
