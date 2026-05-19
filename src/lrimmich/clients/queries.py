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
    has_caption = "caption" in columns
    has_touch_time = "touchTime" in columns
    has_stack = "stack" in columns
    if (has_caption and has_touch_time) or has_caption:
        version = LrVersion.V7_PLUS
    else:
        version = LrVersion.V6
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

COLLECTION_COVERS = """
    SELECT ci.collection,
           af.pathFromRoot || lf.idx_filename AS path,
           COALESCE(ai.rating, 0) AS rating,
           COALESCE(ai.pick, 0) AS pick
    FROM AgLibraryCollectionImage ci
    JOIN Adobe_images ai ON ci.image = ai.id_local
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
"""

FLAGGED_IMAGES = f"{SELECT_PATH}{IMAGE_PATH_JOIN}    WHERE ai.pick = 1"

REJECTED_IMAGES = f"{SELECT_PATH}{IMAGE_PATH_JOIN}    WHERE ai.pick = -1"

RATED_IMAGES = f"{SELECT_PATH}, ai.rating{IMAGE_PATH_JOIN}    WHERE ai.rating > 0"

COLOR_LABELS = (
    f"{SELECT_PATH}, ai.colorLabels{IMAGE_PATH_JOIN}    WHERE ai.colorLabels != ''"
)

CAPTIONS = (
    f"{SELECT_PATH}, ai.caption{IMAGE_PATH_JOIN}"
    "    WHERE ai.caption IS NOT NULL AND ai.caption != ''"
)

KEYWORDS_TREE = "SELECT id_local, name, parent FROM AgLibraryKeyword"

KEYWORD_IMAGES = """
    SELECT af.pathFromRoot, lf.idx_filename, ki.tag
    FROM AgLibraryKeywordImage ki
    JOIN Adobe_images ai ON ki.image = ai.id_local
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
"""

STACKS = """
    SELECT ai.stack, af.pathFromRoot || lf.idx_filename AS path,
           ai.stackPosition
    FROM Adobe_images ai
    JOIN AgLibraryFile lf ON ai.rootFile = lf.id_local
    JOIN AgLibraryFolder af ON lf.folder = af.id_local
    WHERE ai.stack IS NOT NULL
    ORDER BY ai.stack, ai.stackPosition
"""

FINGERPRINT_COUNTS = """
    SELECT MAX(touchTime) AS max_touch,
           COUNT(*) AS img_count
    FROM Adobe_images
"""

COLLECTION_IMAGE_COUNT = "SELECT COUNT(*) AS cnt FROM AgLibraryCollectionImage"

CHANGED_PATHS = f"""
    SELECT af.pathFromRoot || lf.idx_filename AS path
    {IMAGE_PATH_JOIN}
    WHERE ai.touchTime > ?
"""

MAX_TOUCH_TIME = "SELECT MAX(touchTime) AS mt FROM Adobe_images"
