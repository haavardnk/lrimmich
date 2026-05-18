import sqlite3
import tomllib
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB
from lrimmich.utils.config import Config
from lrimmich.utils.resolver import map_path


def _derive_section_models() -> tuple[
    dict[str, type[BaseModel]], dict[str, type[BaseModel]]
]:
    sections: dict[str, type[BaseModel]] = {}
    list_sections: dict[str, type[BaseModel]] = {}
    for name, info in Config.model_fields.items():
        ann = info.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            sections[name] = ann
        elif get_origin(ann) is list:
            args = get_args(ann)
            if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                list_sections[name] = args[0]
    return sections, list_sections


_SECTION_MODELS, _LIST_SECTION_MODELS = _derive_section_models()


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


def check_immich_reachable(client: ImmichClient) -> CheckResult:
    try:
        client.server_about()
        return CheckResult("immich", True, "Reachable")
    except Exception as e:
        return CheckResult("immich", False, str(e))


def check_api_permissions(client: ImmichClient) -> CheckResult:
    try:
        client.get_albums()
        client.get_tags()
        return CheckResult("api_perms", True, "Key has needed permissions")
    except Exception as e:
        return CheckResult("api_perms", False, str(e))


def check_path_mapping(
    immich_library_path: str,
    catalog: Path,
    client: ImmichClient,
    strip: str = "",
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
        expected = map_path(relative_path, immich_library_path, strip)
        expected_folder = expected.rsplit("/", 1)[0]
        assets = client.get_folder_assets(expected_folder)
        for asset in assets:
            if asset.get("originalPath", "") == expected:
                return CheckResult("path_mapping", True, f"Verified: {expected}")
        return CheckResult(
            "path_mapping",
            False,
            f"No asset matched (expected {expected})",
        )
    except Exception as e:
        return CheckResult("path_mapping", False, str(e))


def check_state_db(state: StateDB) -> CheckResult:
    try:
        state.set_meta("doctor_check", "ok")
        val = state.get_meta("doctor_check")
        if val != "ok":
            return CheckResult("state_db", False, "Read-back failed")
        return CheckResult("state_db", True, "Writable")
    except Exception as e:
        return CheckResult("state_db", False, str(e))


def _find_unknown_keys(raw: dict[str, Any]) -> list[str]:
    unknown: list[str] = []
    top_valid = set(Config.model_fields.keys())
    for key in raw:
        if key not in top_valid:
            unknown.append(key)
            continue
        model = _SECTION_MODELS.get(key)
        if model and isinstance(raw[key], dict):
            section_valid = set(model.model_fields.keys())
            for sub_key in raw[key]:
                if sub_key not in section_valid:
                    unknown.append(f"{key}.{sub_key}")
    return unknown


def check_config_keys(config_path: Path) -> CheckResult:
    try:
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)
    except Exception as e:
        return CheckResult("config", False, f"Failed to read: {e}")
    unknown = _find_unknown_keys(raw)
    if unknown:
        return CheckResult("config", False, f"Unknown keys: {', '.join(unknown)}")
    return CheckResult("config", True, "Valid")


def run_doctor(
    cfg: Config,
    client: ImmichClient,
    state: StateDB,
    config_path: Path | None = None,
) -> DoctorReport:
    report = DoctorReport()
    if config_path:
        report.checks.append(check_config_keys(config_path))
    report.checks.append(check_catalog(cfg.lightroom.catalog))
    report.checks.append(check_wal_lock(cfg.lightroom.catalog))
    report.checks.append(check_immich_reachable(client))
    report.checks.append(check_api_permissions(client))
    report.checks.append(
        check_path_mapping(
            cfg.immich.library_path,
            cfg.lightroom.catalog,
            client,
            cfg.lightroom.strip,
        )
    )
    report.checks.append(check_state_db(state))
    return report
