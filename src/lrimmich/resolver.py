from lrimmich.config import PathMapping
from lrimmich.immich import ImmichClient


def map_path(relative_path: str, path_map: list[PathMapping]) -> str:
    for mapping in path_map:
        if relative_path.startswith(mapping.lr_path):
            return mapping.immich_path + relative_path[len(mapping.lr_path) :]
    return relative_path


def _filename_from_path(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def resolve_paths(
    relative_paths: set[str],
    path_map: list[PathMapping],
    client: ImmichClient,
) -> dict[str, str]:
    filename_to_paths: dict[str, list[str]] = {}
    for rp in relative_paths:
        fn = _filename_from_path(rp)
        filename_to_paths.setdefault(fn, []).append(rp)

    cache: dict[str, str] = {}
    for filename, paths in filename_to_paths.items():
        results = client.search_metadata(filename)
        if not results:
            continue
        for rp in paths:
            expected = map_path(rp, path_map)
            for asset in results:
                orig = asset.get("originalPath", "")
                if orig == expected and not asset.get("isTrashed", False):
                    cache[rp] = asset["id"]
                    break

    return cache
