from collections.abc import Callable

from lrimmich.immich import ImmichClient
from lrimmich.state import StateDB


def map_path(relative_path: str, immich_library_path: str, strip: str = "") -> str:
    if strip and relative_path.startswith(strip):
        relative_path = relative_path[len(strip) :]
    return immich_library_path + relative_path


def _build_immich_index(
    immich_library_path: str,
    client: ImmichClient,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    all_folders = client.get_folder_paths()
    if immich_library_path:
        prefix = immich_library_path.rstrip("/")
        relevant = [f for f in all_folders if f == prefix or f.startswith(prefix + "/")]
    else:
        relevant = all_folders
    index: dict[str, str] = {}
    total = len(relevant)
    for i, folder in enumerate(relevant):
        if on_progress:
            on_progress(i + 1, total)
        assets = client.get_folder_assets(folder)
        for asset in assets:
            orig = asset.get("originalPath", "")
            if orig and not asset.get("isTrashed", False):
                index[orig] = asset["id"]
    return index


def resolve_paths(
    relative_paths: set[str],
    immich_library_path: str,
    client: ImmichClient,
    state: StateDB | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    strip: str = "",
) -> dict[str, str]:
    cached: dict[str, str] = {}
    missing: set[str] = set()
    if state:
        all_cached = state.get_all_cached_paths()
        for rp in relative_paths:
            if rp in all_cached:
                cached[rp] = all_cached[rp]
            else:
                missing.add(rp)
    else:
        missing = relative_paths

    if missing:
        index = _build_immich_index(immich_library_path, client, on_progress)
        for rp in missing:
            expected = map_path(rp, immich_library_path, strip)
            asset_id = index.get(expected)
            if asset_id:
                cached[rp] = asset_id
    return cached
