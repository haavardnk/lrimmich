import sqlite3
import tomllib
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args, get_origin

import httpx
from pydantic import BaseModel

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB, state_path_for_catalog
from lrimmich.utils.config import Config
from lrimmich.utils.resolver import map_path


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)


def check_catalog(catalog: Path) -> CheckResult:
    if not catalog.exists():
        return CheckResult("catalog", False, f"Not found: {catalog}")
    try:
        with closing(sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)) as conn:
            conn.execute("SELECT id_local FROM AgLibraryCollection LIMIT 1")
    except sqlite3.OperationalError as e:
        return CheckResult("catalog", False, str(e))
    return CheckResult("catalog", True, "Readable")


def check_wal_lock(catalog: Path) -> CheckResult:
    wal = catalog.parent / (catalog.name + "-wal")
    if not wal.exists():
        return CheckResult("wal_lock", True, "No WAL file")
    try:
        with closing(sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        return CheckResult("wal_lock", True, "WAL not locked")
    except sqlite3.OperationalError:
        return CheckResult("wal_lock", False, "WAL locked (Lightroom open?)")


async def check_immich_reachable(client: ImmichClient) -> CheckResult:
    try:
        await client.server_about()
        return CheckResult("immich", True, "Reachable")
    except httpx.HTTPError as e:
        return CheckResult("immich", False, str(e))


async def check_api_permissions(client: ImmichClient) -> CheckResult:
    try:
        await client.get_albums()
        await client.get_tags()
        return CheckResult("api_perms", True, "Key has needed permissions")
    except httpx.HTTPError as e:
        return CheckResult("api_perms", False, str(e))


async def check_path_mapping(
    library_paths: list[str],
    catalog: Path,
    client: ImmichClient,
    strip: str | None = None,
) -> CheckResult:
    try:
        with closing(sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT af.pathFromRoot, lf.idx_filename "
                "FROM AgLibraryFile lf "
                "JOIN AgLibraryFolder af ON lf.folder = af.id_local "
                "LIMIT 1"
            ).fetchone()
        if not row:
            return CheckResult("path_mapping", False, "No files in catalog")
        relative_path = row["pathFromRoot"] + row["idx_filename"]
        for lp in library_paths:
            expected = map_path(relative_path, lp, strip)
            expected_folder = expected.rsplit("/", 1)[0]
            assets = await client.get_folder_assets(expected_folder)
            for asset in assets:
                if asset.get("originalPath", "") == expected:
                    return CheckResult("path_mapping", True, f"Verified: {expected}")
        return CheckResult(
            "path_mapping",
            False,
            "No asset matched for any library path",
        )
    except (httpx.HTTPError, sqlite3.Error) as e:
        return CheckResult("path_mapping", False, str(e))


def check_state_db(state: StateDB) -> CheckResult:
    try:
        state.set_meta("doctor_check", "ok")
        val = state.get_meta("doctor_check")
        if val != "ok":
            return CheckResult("state_db", False, "Read-back failed")
        return CheckResult("state_db", True, "Writable")
    except sqlite3.Error as e:
        return CheckResult("state_db", False, str(e))


def _find_unknown_keys(raw: dict[str, Any]) -> list[str]:
    unknown: list[str] = []
    for key in raw:
        if key not in Config.model_fields:
            unknown.append(key)
            continue
        ann = Config.model_fields[key].annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            if isinstance(raw[key], dict):
                for sub_key in raw[key]:
                    if sub_key not in ann.model_fields:
                        unknown.append(f"{key}.{sub_key}")
        elif get_origin(ann) is list and isinstance(raw[key], list):
            args = get_args(ann)
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                item_model = args[0]
                for index, item in enumerate(raw[key]):
                    if not isinstance(item, dict):
                        continue
                    for sub_key in item:
                        if sub_key not in item_model.model_fields:
                            unknown.append(f"{key}[{index}].{sub_key}")
    return unknown


def check_config_keys(config_path: Path) -> CheckResult:
    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        return CheckResult("config", False, f"Failed to read: {e}")
    unknown = _find_unknown_keys(raw)
    if unknown:
        return CheckResult("config", False, f"Unknown keys: {', '.join(unknown)}")
    return CheckResult("config", True, "Valid")


async def run_doctor(
    cfg: Config,
    client: ImmichClient,
    config_path: Path | None = None,
) -> DoctorReport:
    report = DoctorReport()
    if config_path:
        report.checks.append(check_config_keys(config_path))
    report.checks.append(await check_immich_reachable(client))
    report.checks.append(await check_api_permissions(client))
    for catalog in cfg.catalogs:
        report.checks.append(check_catalog(catalog.catalog))
        report.checks.append(check_wal_lock(catalog.catalog))
        report.checks.append(
            await check_path_mapping(
                cfg.immich.library_paths,
                catalog.catalog,
                client,
                catalog.strip,
            )
        )
        state = StateDB(state_path_for_catalog(catalog.key))
        try:
            report.checks.append(check_state_db(state))
        finally:
            state.close()
    return report
