import sqlite3
from collections import defaultdict
from contextlib import closing
from fnmatch import fnmatch
from pathlib import Path

from lrimmich.utils.config import BaseConfig, ExcludeConfig


class LrCollection(BaseConfig):
    id: int
    name: str
    full_name: str
    relative_paths: list[str]


def _connect(catalog: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _build_full_name(
    collection_id: int,
    tree: dict[int, tuple[str, int | None]],
) -> str:
    parts: list[str] = []
    current: int | None = collection_id
    while current is not None and current in tree:
        name, parent_id = tree[current]
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


def _read_collections_inner(
    conn: sqlite3.Connection,
    exclude: ExcludeConfig | None,
) -> list[LrCollection]:
    all_rows = conn.execute(
        "SELECT id_local, name, parent FROM AgLibraryCollection"
    ).fetchall()
    tree: dict[int, tuple[str, int | None]] = {
        r["id_local"]: (r["name"], r["parent"]) for r in all_rows
    }

    exclude_parent_ids = set(exclude.parent_ids) if exclude else set()
    exclude_patterns = exclude.name_patterns if exclude else []

    rows = conn.execute("""
        SELECT id_local, name, parent
        FROM AgLibraryCollection
        WHERE creationId = 'com.adobe.ag.library.collection'
          AND systemOnly != '1.0'
    """).fetchall()

    collection_ids = [
        row["id_local"]
        for row in rows
        if not (row["parent"] is not None and row["parent"] in exclude_parent_ids)
        and not any(
            fnmatch(_build_full_name(row["id_local"], tree), pat)
            for pat in exclude_patterns
        )
    ]

    files_by_collection: dict[int, list[str]] = defaultdict(list)
    if collection_ids:
        placeholders = ",".join("?" * len(collection_ids))
        file_rows = conn.execute(
            f"""
            SELECT ci.collection, af.pathFromRoot, lf.idx_filename
            FROM AgLibraryCollectionImage ci
            JOIN Adobe_images ai ON ci.image = ai.id_local
            JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
            JOIN AgLibraryFolder af ON lf.folder = af.id_local
            WHERE ci.collection IN ({placeholders})
            """,
            collection_ids,
        ).fetchall()
        for f in file_rows:
            files_by_collection[f["collection"]].append(
                f["pathFromRoot"] + f["idx_filename"]
            )

    collections: list[LrCollection] = []
    for row in rows:
        col_id: int = row["id_local"]
        parent_id: int | None = row["parent"]
        if parent_id is not None and parent_id in exclude_parent_ids:
            continue

        full_name = _build_full_name(col_id, tree)
        if any(fnmatch(full_name, pat) for pat in exclude_patterns):
            continue

        collections.append(
            LrCollection(
                id=col_id,
                name=row["name"],
                full_name=full_name,
                relative_paths=files_by_collection.get(col_id, []),
            )
        )

    return collections


def read_collection_covers(catalog: Path) -> dict[int, str]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute("""
            SELECT ci.collection,
                   af.pathFromRoot || lf.idx_filename AS path,
                   COALESCE(ai.rating, 0) AS rating,
                   COALESCE(ai.pick, 0) AS pick
            FROM AgLibraryCollectionImage ci
            JOIN Adobe_images ai ON ci.image = ai.id_local
            JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
            JOIN AgLibraryFolder af ON lf.folder = af.id_local
        """).fetchall()

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


def read_flagged_images(catalog: Path) -> set[str]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute("""
            SELECT af.pathFromRoot, lf.idx_filename
            FROM Adobe_images ai
            JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
            JOIN AgLibraryFolder af ON lf.folder = af.id_local
            WHERE ai.pick = 1
        """).fetchall()
        return {r["pathFromRoot"] + r["idx_filename"] for r in rows}


def read_rejected_images(catalog: Path) -> set[str]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute("""
            SELECT af.pathFromRoot, lf.idx_filename
            FROM Adobe_images ai
            JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
            JOIN AgLibraryFolder af ON lf.folder = af.id_local
            WHERE ai.pick = -1
        """).fetchall()
        return {r["pathFromRoot"] + r["idx_filename"] for r in rows}


def read_rated_images(catalog: Path) -> dict[str, int]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute("""
            SELECT af.pathFromRoot, lf.idx_filename, ai.rating
            FROM Adobe_images ai
            JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
            JOIN AgLibraryFolder af ON lf.folder = af.id_local
            WHERE ai.rating > 0
        """).fetchall()
        return {r["pathFromRoot"] + r["idx_filename"]: r["rating"] for r in rows}


def read_color_labels(catalog: Path) -> dict[str, str]:
    with closing(_connect(catalog)) as conn:
        rows = conn.execute("""
            SELECT af.pathFromRoot, lf.idx_filename, ai.colorLabels
            FROM Adobe_images ai
            JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
            JOIN AgLibraryFolder af ON lf.folder = af.id_local
            WHERE ai.colorLabels != ''
        """).fetchall()
        return {r["pathFromRoot"] + r["idx_filename"]: r["colorLabels"] for r in rows}


def _build_keyword_hierarchy(
    keyword_id: int,
    tree: dict[int, tuple[str, int | None]],
) -> str:
    parts: list[str] = []
    current: int | None = keyword_id
    while current is not None and current in tree:
        name, parent_id = tree[current]
        parts.append(name)
        current = parent_id
    parts.reverse()
    return "/".join(parts)


def read_keywords(catalog: Path) -> dict[str, list[str]]:
    with closing(_connect(catalog)) as conn:
        return _read_keywords_inner(conn)


def _read_keywords_inner(conn: sqlite3.Connection) -> dict[str, list[str]]:
    kw_rows = conn.execute(
        "SELECT id_local, name, parent FROM AgLibraryKeyword"
    ).fetchall()
    tree: dict[int, tuple[str, int | None]] = {
        r["id_local"]: (r["name"], r["parent"]) for r in kw_rows
    }

    rows = conn.execute("""
        SELECT af.pathFromRoot, lf.idx_filename, ki.tag
        FROM AgLibraryKeywordImage ki
        JOIN Adobe_images ai ON ki.image = ai.id_local
        JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
        JOIN AgLibraryFolder af ON lf.folder = af.id_local
    """).fetchall()

    result: dict[str, list[str]] = {}
    for r in rows:
        path = r["pathFromRoot"] + r["idx_filename"]
        hierarchy = _build_keyword_hierarchy(r["tag"], tree)
        result.setdefault(path, []).append(hierarchy)

    return result
