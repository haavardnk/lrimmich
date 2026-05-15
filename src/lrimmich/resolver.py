from collections.abc import Callable

from lrimmich.config import PathMapping
from lrimmich.immich import ImmichClient


def map_path(relative_path: str, path_map: list[PathMapping]) -> str:
    for mapping in path_map:
        if relative_path.startswith(mapping.lr_path):
            return mapping.immich_path + relative_path[len(mapping.lr_path) :]
    return relative_path


def _folder_from_path(path: str) -> str:
    idx = path.rfind("/")
    return path[: idx + 1] if idx >= 0 else ""


def _build_immich_index(
    path_map: list[PathMapping],
    client: ImmichClient,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    all_folders = client.get_folder_paths()
    if path_map:
        immich_prefixes = {m.immich_path.rstrip("/") for m in path_map}
        relevant = [
            f
            for f in all_folders
            if any(f == p or f.startswith(p + "/") for p in immich_prefixes)
        ]
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
    path_map: list[PathMapping],
    client: ImmichClient,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    index = _build_immich_index(path_map, client, on_progress)
    cache: dict[str, str] = {}
    for rp in relative_paths:
        expected = map_path(rp, path_map)
        asset_id = index.get(expected)
        if asset_id:
            cache[rp] = asset_id
    return cache
