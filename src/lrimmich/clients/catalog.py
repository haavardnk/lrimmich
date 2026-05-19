import sqlite3
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from fnmatch import fnmatch
from hashlib import sha256
from pathlib import Path

from lrimmich.clients.queries import (
    CAPTIONS,
    CHANGED_PATHS,
    COLLECTION_COVERS,
    COLLECTION_FILES,
    COLLECTION_IMAGE_COUNT,
    COLLECTION_TREE,
    COLLECTIONS_ALL,
    COLLECTIONS_VISIBLE,
    COLOR_LABELS,
    FINGERPRINT_COUNTS,
    FLAGGED_IMAGES,
    KEYWORD_IMAGES,
    KEYWORDS_TREE,
    MAX_TOUCH_TIME,
    RATED_IMAGES,
    REJECTED_IMAGES,
    STACKS,
    LrSchema,
    detect_schema,
)
from lrimmich.utils.config import BaseConfig, ExcludeConfig


class LrCollection(BaseConfig):
    id: int
    name: str
    full_name: str
    relative_paths: list[str]


class LrCollectionTreeNode(BaseConfig):
    id: int
    name: str
    full_name: str
    kind: str
    children: list["LrCollectionTreeNode"]


def _connect(catalog: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _detect(catalog: Path) -> LrSchema:
    with closing(_connect(catalog)) as conn:
        return detect_schema(conn)


def _walk_ancestors(
    node_id: int,
    tree: dict[int, tuple[str | None, int | None]],
) -> str:
    parts: list[str] = []
    current: int | None = node_id
    while current is not None and current in tree:
        name, parent_id = tree[current]
        if name is not None:
            parts.append(name)
        current = parent_id
    parts.reverse()
    return "/".join(parts)


def read_collections(
    catalog: Path,
    exclude: ExcludeConfig | None = None,
) -> list[LrCollection]:
    with closing(_connect(catalog)) as conn:
        return _read_collections_inner(conn, exclude)


def read_collection_tree(catalog: Path) -> list[LrCollectionTreeNode]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute(COLLECTION_TREE).fetchall()

    all_items: dict[int, tuple[str | None, int | None]] = {
        r["id_local"]: (r["name"], r["parent"]) for r in rows
    }

    kind_map: dict[str, str] = {
        "com.adobe.ag.library.collection": "collection",
        "com.adobe.ag.library.group": "set",
    }

    nodes: dict[int, LrCollectionTreeNode] = {}
    for r in rows:
        rid: int = r["id_local"]
        nodes[rid] = LrCollectionTreeNode(
            id=rid,
            name=r["name"],
            full_name=_walk_ancestors(rid, all_items),
            kind=kind_map.get(r["creationId"], r["creationId"]),
            children=[],
        )

    roots: list[LrCollectionTreeNode] = []
    for r in rows:
        rid = r["id_local"]
        parent: int | None = r["parent"]
        if parent is not None and parent in nodes:
            nodes[parent].children.append(nodes[rid])
        else:
            roots.append(nodes[rid])

    return roots


def _read_collections_inner(
    conn: sqlite3.Connection,
    exclude: ExcludeConfig | None,
) -> list[LrCollection]:
    all_rows = conn.execute(COLLECTIONS_ALL).fetchall()
    tree: dict[int, tuple[str | None, int | None]] = {
        r["id_local"]: (r["name"], r["parent"]) for r in all_rows
    }

    exclude_ids = set(exclude.collection_ids) if exclude else set()
    exclude_patterns = exclude.name_patterns if exclude else []

    def _is_excluded(col_id: int) -> bool:
        current: int | None = col_id
        while current is not None and current in tree:
            if current in exclude_ids:
                return True
            current = tree[current][1]
        return False

    rows = conn.execute(COLLECTIONS_VISIBLE).fetchall()

    kept_rows: list[tuple[sqlite3.Row, str]] = []
    for row in rows:
        col_id: int = row["id_local"]
        if _is_excluded(col_id):
            continue
        full_name = _walk_ancestors(col_id, tree)
        if any(fnmatch(full_name, pat) for pat in exclude_patterns):
            continue
        kept_rows.append((row, full_name))

    collection_ids = [row["id_local"] for row, _ in kept_rows]

    files_by_collection: dict[int, list[str]] = defaultdict(list)
    if collection_ids:
        placeholders = ",".join("?" * len(collection_ids))
        file_rows = conn.execute(
            COLLECTION_FILES.format(placeholders=placeholders),
            collection_ids,
        ).fetchall()
        for f in file_rows:
            files_by_collection[f["collection"]].append(
                f["pathFromRoot"] + f["idx_filename"]
            )

    return [
        LrCollection(
            id=row["id_local"],
            name=row["name"],
            full_name=full_name,
            relative_paths=files_by_collection.get(row["id_local"], []),
        )
        for row, full_name in kept_rows
    ]


def read_collection_covers(catalog: Path) -> dict[int, str]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute(COLLECTION_COVERS).fetchall()

        best: dict[int, tuple[str, int, int]] = {}
        for r in rows:
            col_id: int = r["collection"]
            path: str = r["path"]
            rating: int = r["rating"]
            pick: int = r["pick"]
            prev = best.get(col_id)
            if prev is None or (rating, pick) > (prev[1], prev[2]):
                best[col_id] = (path, rating, pick)

        result: dict[int, str] = {}
        for col_id, (path, rating, pick) in best.items():
            if rating > 0 or pick > 0:
                result[col_id] = path

        return result


def _query_rows(catalog: Path, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with closing(_connect(catalog)) as conn:
        return conn.execute(sql, params).fetchall()


def read_flagged_images(catalog: Path) -> set[str]:
    rows = _query_rows(catalog, FLAGGED_IMAGES)
    return {r["pathFromRoot"] + r["idx_filename"] for r in rows}


def read_rejected_images(catalog: Path) -> set[str]:
    rows = _query_rows(catalog, REJECTED_IMAGES)
    return {r["pathFromRoot"] + r["idx_filename"] for r in rows}


def read_rated_images(catalog: Path) -> dict[str, int]:
    rows = _query_rows(catalog, RATED_IMAGES)
    return {r["pathFromRoot"] + r["idx_filename"]: r["rating"] for r in rows}


def read_color_labels(catalog: Path) -> dict[str, str]:
    rows = _query_rows(catalog, COLOR_LABELS)
    return {r["pathFromRoot"] + r["idx_filename"]: r["colorLabels"] for r in rows}


def read_captions(catalog: Path) -> dict[str, str]:
    rows = _query_rows(catalog, CAPTIONS)
    return {r["pathFromRoot"] + r["idx_filename"]: r["caption"] for r in rows}


def read_keywords(catalog: Path) -> dict[str, list[str]]:
    with closing(_connect(catalog)) as conn:
        return _read_keywords_inner(conn)


def _read_keywords_inner(conn: sqlite3.Connection) -> dict[str, list[str]]:
    kw_rows = conn.execute(KEYWORDS_TREE).fetchall()
    tree: dict[int, tuple[str | None, int | None]] = {
        r["id_local"]: (r["name"], r["parent"]) for r in kw_rows
    }

    rows = conn.execute(KEYWORD_IMAGES).fetchall()

    result: dict[str, list[str]] = {}
    for r in rows:
        path = r["pathFromRoot"] + r["idx_filename"]
        hierarchy = _walk_ancestors(r["tag"], tree)
        result.setdefault(path, []).append(hierarchy)

    return result


@dataclass
class LrStack:
    stack_id: int
    paths: list[str]


def read_stacks(catalog: Path) -> list[LrStack]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute(STACKS).fetchall()

    groups: dict[int, list[str]] = {}
    for r in rows:
        groups.setdefault(r["stack"], []).append(r["path"])

    return [
        LrStack(stack_id=sid, paths=paths)
        for sid, paths in groups.items()
        if len(paths) >= 2
    ]


def read_catalog_fingerprint(catalog: Path) -> str:
    with closing(_connect(catalog)) as conn:
        row = conn.execute(FINGERPRINT_COUNTS).fetchone()
        col_row = conn.execute(COLLECTION_IMAGE_COUNT).fetchone()
    parts = f"{row['max_touch']}:{row['img_count']}:{col_row['cnt']}"
    return sha256(parts.encode()).hexdigest()[:16]


def read_changed_paths(catalog: Path, since_touch_time: float) -> set[str]:
    rows = _query_rows(catalog, CHANGED_PATHS, (since_touch_time,))
    return {r["path"] for r in rows}


def read_max_touch_time(catalog: Path) -> float:
    rows = _query_rows(catalog, MAX_TOUCH_TIME)
    return rows[0]["mt"] or 0.0 if rows else 0.0
