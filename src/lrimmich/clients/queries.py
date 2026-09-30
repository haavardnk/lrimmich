import sqlite3
from dataclasses import dataclass
from enum import IntEnum


class LrVersion(IntEnum):
    UNKNOWN = 0
    V6 = 6
    V7_PLUS = 7


@dataclass(frozen=True)
class LrSchema:
    version: LrVersion
    has_caption: bool
    has_touch_time: bool
    has_stack: bool


def detect_schema(conn: sqlite3.Connection) -> LrSchema:
    columns = {
        r["name"] for r in conn.execute("PRAGMA table_info(Adobe_images)").fetchall()
    }
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    has_caption = "AgLibraryIPTC" in tables
    has_touch_time = "touchTime" in columns
    has_stack = "AgLibraryFolderStackImage" in tables
    version = LrVersion.V7_PLUS if has_touch_time else LrVersion.V6
    return LrSchema(
        version=version,
        has_caption=has_caption,
        has_touch_time=has_touch_time,
        has_stack=has_stack,
    )


IMAGE_PATH_JOIN = """
    FROM Adobe_images ai
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
"""

SELECT_PATH = "SELECT af.pathFromRoot, lf.idx_filename"

COLLECTIONS_ALL = "SELECT id_local, name, parent FROM AgLibraryCollection"

COLLECTIONS_VISIBLE = """
    SELECT id_local, name, parent
    FROM AgLibraryCollection
    WHERE creationId = 'com.adobe.ag.library.collection'
      AND systemOnly != '1.0'
"""

COLLECTION_TREE = """
    SELECT id_local, name, parent, creationId
    FROM AgLibraryCollection
    WHERE systemOnly != '1.0'
"""

COLLECTION_FILES = """
    SELECT ci.collection, af.pathFromRoot, lf.idx_filename
    FROM AgLibraryCollectionImage ci
    JOIN Adobe_images ai ON ci.image = ai.id_local
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
    WHERE ci.collection IN ({placeholders})
"""

FLAGGED_IMAGES = f"{SELECT_PATH}{IMAGE_PATH_JOIN}    WHERE ai.pick = 1"

REJECTED_IMAGES = f"{SELECT_PATH}{IMAGE_PATH_JOIN}    WHERE ai.pick = -1"

RATED_IMAGES = f"{SELECT_PATH}, ai.rating{IMAGE_PATH_JOIN}    WHERE ai.rating > 0"

COLOR_LABELS = (
    f"{SELECT_PATH}, ai.colorLabels{IMAGE_PATH_JOIN}    WHERE ai.colorLabels != ''"
)

CAPTIONS = """
    SELECT af.pathFromRoot, lf.idx_filename, iptc.caption
    FROM AgLibraryIPTC iptc
    JOIN Adobe_images ai ON iptc.image = ai.id_local
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
    WHERE iptc.caption IS NOT NULL AND iptc.caption != ''
"""

KEYWORDS_TREE = "SELECT id_local, name, parent FROM AgLibraryKeyword"

KEYWORD_IMAGES = """
    SELECT af.pathFromRoot, lf.idx_filename, ki.tag
    FROM AgLibraryKeywordImage ki
    JOIN Adobe_images ai ON ki.image = ai.id_local
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
"""

STACKS = """
    SELECT si.stack, COALESCE(af.pathFromRoot, '') || lf.idx_filename AS path
    FROM AgLibraryFolderStackImage si
    JOIN Adobe_images ai ON si.image = ai.id_local
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
    ORDER BY si.stack, si.position
"""

STACK_DIGEST = """
    SELECT COUNT(*) AS cnt,
           COALESCE(SUM(stack * 31 + image), 0) AS digest,
           COALESCE(SUM(position * image), 0) AS positions
    FROM AgLibraryFolderStackImage
"""

FINGERPRINT_COUNTS = """
    SELECT MAX(touchTime) AS max_touch,
           COUNT(*) AS img_count
    FROM Adobe_images
"""

COLLECTION_MEMBERSHIP_DIGEST = """
    SELECT COUNT(*) AS cnt,
           COALESCE(SUM(collection * 31 + image), 0) AS digest,
           COALESCE(MAX(id_local), 0) AS max_id
    FROM AgLibraryCollectionImage
"""

KEYWORD_MEMBERSHIP_DIGEST = """
    SELECT COUNT(*) AS cnt,
           COALESCE(SUM(tag * 31 + image), 0) AS digest,
           COALESCE(MAX(id_local), 0) AS max_id
    FROM AgLibraryKeywordImage
"""

COLLECTION_DIGEST = """
    SELECT COUNT(*) AS cnt,
           COALESCE(MAX(id_local), 0) AS max_id
    FROM AgLibraryCollection
"""
