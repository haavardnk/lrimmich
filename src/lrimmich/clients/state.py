import json
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

from platformdirs import user_state_path

DEFAULT_STATE_PATH = user_state_path("lrimmich") / "state.db"

SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS path_cache (
    relative_path TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    original_path TEXT NOT NULL,
    last_verified_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS album_ownership (
    lr_collection_id INTEGER PRIMARY KEY,
    immich_album_id TEXT NOT NULL UNIQUE,
    last_name TEXT NOT NULL,
    last_synced_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS synced_ratings (
    asset_id TEXT PRIMARY KEY,
    rating INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS synced_covers (
    immich_album_id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS synced_favorites (
    asset_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS synced_rejects (
    asset_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    payload_json TEXT
);
"""

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS synced_album_assets (
    immich_album_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    PRIMARY KEY (immich_album_id, asset_id)
);
"""


class StateDB:
    def __init__(self, path: Path = DEFAULT_STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Generator[None]:
        self._conn.execute("BEGIN")
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise

    def _migrate(self) -> None:
        current = self._get_schema_version()
        if current >= SCHEMA_VERSION:
            return
        if current < 1:
            self._conn.executescript(SCHEMA_V1)
        if current < 2:
            self._conn.executescript(SCHEMA_V2)
        self._set_meta("schema_version", str(SCHEMA_VERSION))

    def _get_schema_version(self) -> int:
        try:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            return int(row["value"]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (key, value),
        )

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._set_meta(key, value)

    def get_cached_asset(self, relative_path: str) -> str | None:
        row = self._conn.execute(
            "SELECT asset_id FROM path_cache WHERE relative_path = ?",
            (relative_path,),
        ).fetchone()
        return row["asset_id"] if row else None

    def upsert_path_cache(
        self,
        relative_path: str,
        asset_id: str,
        original_path: str,
    ) -> None:
        now = int(time.time())
        self._conn.execute(
            "INSERT OR REPLACE INTO path_cache"
            "(relative_path, asset_id, original_path, last_verified_at) "
            "VALUES (?, ?, ?, ?)",
            (relative_path, asset_id, original_path, now),
        )

    def upsert_path_cache_bulk(
        self,
        entries: list[tuple[str, str, str]],
    ) -> None:
        now = int(time.time())
        with self.transaction():
            self._conn.executemany(
                "INSERT OR REPLACE INTO path_cache"
                "(relative_path, asset_id, original_path, last_verified_at) "
                "VALUES (?, ?, ?, ?)",
                [(rp, aid, op, now) for rp, aid, op in entries],
            )

    def get_all_cached_paths(self, max_age: int | None = None) -> dict[str, str]:
        if max_age is not None:
            cutoff = int(time.time()) - max_age
            rows = self._conn.execute(
                "SELECT relative_path, asset_id FROM path_cache "
                "WHERE last_verified_at >= ?",
                (cutoff,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT relative_path, asset_id FROM path_cache"
            ).fetchall()
        return {r["relative_path"]: r["asset_id"] for r in rows}

    def clear_path_cache(self) -> None:
        self._conn.execute("DELETE FROM path_cache")

    def get_album_ownership(self, lr_collection_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM album_ownership WHERE lr_collection_id = ?",
            (lr_collection_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_album_by_immich_id(self, immich_album_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM album_ownership WHERE immich_album_id = ?",
            (immich_album_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_all_owned_albums(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM album_ownership").fetchall()
        return [dict(r) for r in rows]

    def upsert_album_ownership(
        self,
        lr_collection_id: int,
        immich_album_id: str,
        name: str,
    ) -> None:
        now = int(time.time())
        self._conn.execute(
            "INSERT OR REPLACE INTO album_ownership"
            "(lr_collection_id, immich_album_id, last_name, last_synced_at) "
            "VALUES (?, ?, ?, ?)",
            (lr_collection_id, immich_album_id, name, now),
        )

    def remove_album_ownership(self, lr_collection_id: int) -> None:
        self._conn.execute(
            "DELETE FROM album_ownership WHERE lr_collection_id = ?",
            (lr_collection_id,),
        )

    def get_synced_ratings(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT asset_id, rating FROM synced_ratings"
        ).fetchall()
        return {r["asset_id"]: r["rating"] for r in rows}

    def replace_synced_ratings(self, ratings: dict[str, int]) -> None:
        with self.transaction():
            self._conn.execute("DELETE FROM synced_ratings")
            self._conn.executemany(
                "INSERT INTO synced_ratings(asset_id, rating) VALUES (?, ?)",
                ratings.items(),
            )

    def get_synced_covers(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT immich_album_id, asset_id FROM synced_covers"
        ).fetchall()
        return {r["immich_album_id"]: r["asset_id"] for r in rows}

    def replace_synced_covers(self, covers: dict[str, str]) -> None:
        with self.transaction():
            self._conn.execute("DELETE FROM synced_covers")
            self._conn.executemany(
                "INSERT INTO synced_covers(immich_album_id, asset_id) VALUES (?, ?)",
                covers.items(),
            )

    def get_synced_favorites(self) -> set[str]:
        rows = self._conn.execute("SELECT asset_id FROM synced_favorites").fetchall()
        return {r["asset_id"] for r in rows}

    def replace_synced_favorites(self, asset_ids: set[str]) -> None:
        self._replace_asset_set("synced_favorites", asset_ids)

    def get_synced_rejects(self) -> set[str]:
        rows = self._conn.execute("SELECT asset_id FROM synced_rejects").fetchall()
        return {r["asset_id"] for r in rows}

    def replace_synced_rejects(self, asset_ids: set[str]) -> None:
        self._replace_asset_set("synced_rejects", asset_ids)

    def _replace_asset_set(self, table: str, asset_ids: set[str]) -> None:
        with self.transaction():
            self._conn.execute(f"DELETE FROM {table}")
            self._conn.executemany(
                f"INSERT INTO {table}(asset_id) VALUES (?)",
                [(aid,) for aid in asset_ids],
            )

    def append_audit_log(
        self,
        action: str,
        target_type: str,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = int(time.time())
        payload_json = json.dumps(payload) if payload else None
        self._conn.execute(
            "INSERT INTO audit_log(ts, action, target_type, target_id, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, action, target_type, target_id, payload_json),
        )

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_synced_album_assets(self, immich_album_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT asset_id FROM synced_album_assets WHERE immich_album_id = ?",
            (immich_album_id,),
        ).fetchall()
        return {r["asset_id"] for r in rows}

    def replace_synced_album_assets(
        self, immich_album_id: str, asset_ids: set[str]
    ) -> None:
        with self.transaction():
            self._conn.execute(
                "DELETE FROM synced_album_assets WHERE immich_album_id = ?",
                (immich_album_id,),
            )
            self._conn.executemany(
                "INSERT INTO synced_album_assets(immich_album_id, asset_id) "
                "VALUES (?, ?)",
                [(immich_album_id, aid) for aid in asset_ids],
            )

    def add_synced_album_assets(
        self, immich_album_id: str, asset_ids: set[str]
    ) -> None:
        with self.transaction():
            self._conn.executemany(
                "INSERT OR IGNORE INTO synced_album_assets"
                "(immich_album_id, asset_id) VALUES (?, ?)",
                [(immich_album_id, aid) for aid in asset_ids],
            )

    def remove_synced_album_assets(
        self, immich_album_id: str, asset_ids: set[str]
    ) -> None:
        with self.transaction():
            self._conn.executemany(
                "DELETE FROM synced_album_assets "
                "WHERE immich_album_id = ? AND asset_id = ?",
                [(immich_album_id, aid) for aid in asset_ids],
            )

    def clear_synced_album_assets(self, immich_album_id: str) -> None:
        self._conn.execute(
            "DELETE FROM synced_album_assets WHERE immich_album_id = ?",
            (immich_album_id,),
        )

    def close(self) -> None:
        self._conn.close()
