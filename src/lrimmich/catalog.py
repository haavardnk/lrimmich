import sqlite3
from fnmatch import fnmatch
from pathlib import Path

from pydantic import ConfigDict

from lrimmich.config import BaseConfig, ExcludeConfig


class LrCollection(BaseConfig):
    model_config = ConfigDict(extra="forbid")

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
    conn = _connect(catalog)

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

    collections: list[LrCollection] = []
    for row in rows:
        parent_id: int | None = row["parent"]
        if parent_id is not None and parent_id in exclude_parent_ids:
            continue

        full_name = _build_full_name(row["id_local"], tree)

        if any(fnmatch(full_name, pat) for pat in exclude_patterns):
            continue

        files = conn.execute(
            """
            SELECT af.pathFromRoot, lf.idx_filename
            FROM AgLibraryCollectionImage ci
            JOIN Adobe_images ai ON ci.image = ai.id_local
            JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
            JOIN AgLibraryFolder af ON lf.folder = af.id_local
            WHERE ci.collection = ?
            """,
            (row["id_local"],),
        ).fetchall()

        relative_paths = [f["pathFromRoot"] + f["idx_filename"] for f in files]

        collections.append(
            LrCollection(
                id=row["id_local"],
                name=row["name"],
                full_name=full_name,
                relative_paths=relative_paths,
            )
        )

    conn.close()
    return collections


def read_collection_covers(catalog: Path) -> dict[int, str]:
    conn = _connect(catalog)
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

    conn.close()
    return result


def read_flagged_images(catalog: Path) -> set[str]:
    conn = _connect(catalog)
    rows = conn.execute("""
        SELECT af.pathFromRoot, lf.idx_filename
        FROM Adobe_images ai
        JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
        JOIN AgLibraryFolder af ON lf.folder = af.id_local
        WHERE ai.pick = 1
    """).fetchall()
    result = {r["pathFromRoot"] + r["idx_filename"] for r in rows}
    conn.close()
    return result


def read_rejected_images(catalog: Path) -> set[str]:
    conn = _connect(catalog)
    rows = conn.execute("""
        SELECT af.pathFromRoot, lf.idx_filename
        FROM Adobe_images ai
        JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
        JOIN AgLibraryFolder af ON lf.folder = af.id_local
        WHERE ai.pick = -1
    """).fetchall()
    result = {r["pathFromRoot"] + r["idx_filename"] for r in rows}
    conn.close()
    return result


def read_rated_images(catalog: Path) -> dict[str, int]:
    conn = _connect(catalog)
    rows = conn.execute("""
        SELECT af.pathFromRoot, lf.idx_filename, ai.rating
        FROM Adobe_images ai
        JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
        JOIN AgLibraryFolder af ON lf.folder = af.id_local
        WHERE ai.rating > 0
    """).fetchall()
    result = {r["pathFromRoot"] + r["idx_filename"]: r["rating"] for r in rows}
    conn.close()
    return result


def read_color_labels(catalog: Path) -> dict[str, str]:
    conn = _connect(catalog)
    rows = conn.execute("""
        SELECT af.pathFromRoot, lf.idx_filename, ai.colorLabels
        FROM Adobe_images ai
        JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
        JOIN AgLibraryFolder af ON lf.folder = af.id_local
        WHERE ai.colorLabels != ''
    """).fetchall()
    result = {r["pathFromRoot"] + r["idx_filename"]: r["colorLabels"] for r in rows}
    conn.close()
    return result


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
    conn = _connect(catalog)

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

    conn.close()
    return result
