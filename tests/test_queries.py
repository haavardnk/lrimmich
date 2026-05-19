from pathlib import Path

from lrimmich.clients.queries import LrSchema, LrVersion, detect_schema
from tests.fixtures.catalog_factory import CatalogBuilder


def test_detect_schema_full(tmp_path: Path) -> None:
    catalog = tmp_path / "test.lrcat"
    CatalogBuilder(catalog).build()
    schema = LrSchema(
        version=LrVersion.V7_PLUS,
        has_caption=True,
        has_touch_time=True,
        has_stack=True,
    )
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        result = detect_schema(conn)
    assert result == schema


def test_detect_schema_v6(tmp_path: Path) -> None:
    catalog = tmp_path / "v6.lrcat"
    import sqlite3

    conn = sqlite3.connect(str(catalog))
    conn.executescript("""
        CREATE TABLE Adobe_images (
            id_local INTEGER PRIMARY KEY,
            rootFile INTEGER NOT NULL,
            pick INTEGER DEFAULT 0,
            rating INTEGER DEFAULT 0,
            colorLabels TEXT DEFAULT ''
        );
    """)
    conn.close()

    with sqlite3.connect(f"file:{catalog}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        result = detect_schema(conn)
    assert result.version == LrVersion.V6
    assert not result.has_caption
    assert not result.has_touch_time
    assert not result.has_stack
