import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_STATE_PATH = Path("~/.cache/lrimmich/state.db").expanduser()

SCHEMA_VERSION = 1

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

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    payload_json TEXT
);
"""


class StateDB:
    def __init__(self, path: Path = DEFAULT_STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        current = self._get_schema_version()
        if current < 1:
            self._conn.executescript(SCHEMA_V1)
            self._set_meta("schema_version", str(SCHEMA_VERSION))
            self._conn.commit()

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
        self._conn.commit()

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
        self._conn.commit()

    def get_all_cached_paths(self) -> dict[str, str]:
        rows = self._conn.execute(
            "SELECT relative_path, asset_id FROM path_cache"
        ).fetchall()
        return {r["relative_path"]: r["asset_id"] for r in rows}

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
        self._conn.commit()

    def remove_album_ownership(self, lr_collection_id: int) -> None:
        self._conn.execute(
            "DELETE FROM album_ownership WHERE lr_collection_id = ?",
            (lr_collection_id,),
        )
        self._conn.commit()

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
        self._conn.commit()

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
