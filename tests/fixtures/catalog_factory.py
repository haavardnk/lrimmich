import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE AgLibraryCollection (
    id_local INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent INTEGER,
    creationId TEXT NOT NULL,
    systemOnly TEXT DEFAULT '0.0'
);

CREATE TABLE AgLibraryCollectionImage (
    id_local INTEGER PRIMARY KEY AUTOINCREMENT,
    collection INTEGER NOT NULL,
    image INTEGER NOT NULL
);

CREATE TABLE Adobe_images (
    id_local INTEGER PRIMARY KEY,
    rootFile INTEGER NOT NULL,
    pick INTEGER DEFAULT 0,
    rating INTEGER DEFAULT 0,
    colorLabels TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    touchTime REAL DEFAULT 0.0,
    stack INTEGER,
    stackPosition INTEGER DEFAULT 0
);

CREATE TABLE AgLibraryFile (
    id_local INTEGER PRIMARY KEY,
    folder INTEGER NOT NULL,
    idx_filename TEXT NOT NULL
);

CREATE TABLE AgLibraryFolder (
    id_local INTEGER PRIMARY KEY,
    pathFromRoot TEXT NOT NULL
);

CREATE TABLE AgLibraryKeyword (
    id_local INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent INTEGER
);

CREATE TABLE AgLibraryKeywordImage (
    id_local INTEGER PRIMARY KEY AUTOINCREMENT,
    tag INTEGER NOT NULL,
    image INTEGER NOT NULL
);
"""


class CatalogBuilder:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn = sqlite3.connect(str(path))
        self._conn.executescript(SCHEMA)
        self._folder_ids: dict[str, int] = {}
        self._next_folder_id = 1
        self._next_file_id = 1

    def _ensure_folder(self, path_from_root: str) -> int:
        if path_from_root not in self._folder_ids:
            fid = self._next_folder_id
            self._next_folder_id += 1
            self._conn.execute(
                "INSERT INTO AgLibraryFolder(id_local, pathFromRoot) VALUES (?, ?)",
                (fid, path_from_root),
            )
            self._folder_ids[path_from_root] = fid
        return self._folder_ids[path_from_root]

    def add_set(
        self, id: int, name: str, parent: int | None = None
    ) -> "CatalogBuilder":
        self._conn.execute(
            "INSERT INTO AgLibraryCollection(id_local, name, parent, creationId) "
            "VALUES (?, ?, ?, 'com.adobe.ag.library.group')",
            (id, name, parent),
        )
        return self

    def add_collection(
        self, id: int, name: str, parent: int | None = None
    ) -> "CatalogBuilder":
        self._conn.execute(
            "INSERT INTO AgLibraryCollection(id_local, name, parent, creationId) "
            "VALUES (?, ?, ?, 'com.adobe.ag.library.collection')",
            (id, name, parent),
        )
        return self

    def add_system_collection(
        self, id: int, name: str, parent: int | None = None
    ) -> "CatalogBuilder":
        self._conn.execute(
            "INSERT INTO AgLibraryCollection"
            "(id_local, name, parent, creationId, systemOnly) "
            "VALUES (?, ?, ?, 'com.adobe.ag.library.collection', '1.0')",
            (id, name, parent),
        )
        return self

    def add_image(
        self,
        id: int,
        filename: str,
        folder_path: str,
        pick: int = 0,
        rating: int = 0,
        color_labels: str = "",
        caption: str = "",
        touch_time: float = 0.0,
        stack: int | None = None,
        stack_position: int = 0,
    ) -> "CatalogBuilder":
        folder_id = self._ensure_folder(folder_path)
        file_id = self._next_file_id
        self._next_file_id += 1
        self._conn.execute(
            "INSERT INTO AgLibraryFile(id_local, folder, idx_filename) "
            "VALUES (?, ?, ?)",
            (file_id, folder_id, filename),
        )
        self._conn.execute(
            "INSERT INTO Adobe_images"
            "(id_local, rootFile, pick, rating, colorLabels, caption,"
            " touchTime, stack, stackPosition) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                id,
                file_id,
                pick,
                rating,
                color_labels,
                caption,
                touch_time,
                stack,
                stack_position,
            ),
        )
        return self

    def add_collection_image(
        self, collection_id: int, image_id: int
    ) -> "CatalogBuilder":
        self._conn.execute(
            "INSERT INTO AgLibraryCollectionImage(collection, image) VALUES (?, ?)",
            (collection_id, image_id),
        )
        return self

    def add_keyword(
        self, id: int, name: str, parent: int | None = None
    ) -> "CatalogBuilder":
        self._conn.execute(
            "INSERT INTO AgLibraryKeyword(id_local, name, parent) VALUES (?, ?, ?)",
            (id, name, parent),
        )
        return self

    def add_keyword_image(self, keyword_id: int, image_id: int) -> "CatalogBuilder":
        self._conn.execute(
            "INSERT INTO AgLibraryKeywordImage(tag, image) VALUES (?, ?)",
            (keyword_id, image_id),
        )
        return self

    def build(self) -> Path:
        self._conn.commit()
        self._conn.close()
        return self._path
