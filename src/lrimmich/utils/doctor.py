import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lrimmich.clients.catalog import connect
from lrimmich.clients.immich import ImmichClient
from lrimmich.clients.state import StateDB, state_path_for_catalog
from lrimmich.utils.config import Config
from lrimmich.utils.resolver import map_path

MIN_IMMICH_MAJOR = 3


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
        with closing(connect(catalog)) as conn:
            conn.execute("SELECT id_local FROM AgLibraryCollection LIMIT 1")
    except sqlite3.OperationalError as e:
        return CheckResult("catalog", False, str(e))
    return CheckResult("catalog", True, "Readable")


def check_wal_lock(catalog: Path) -> CheckResult:
    wal = catalog.parent / (catalog.name + "-wal")
    if not wal.exists():
        return CheckResult("wal_lock", True, "No WAL file")
    try:
        with closing(connect(catalog)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
        return CheckResult("wal_lock", True, "WAL not locked")
    except sqlite3.OperationalError:
        return CheckResult(
            "wal_lock",
            False,
            "Catalog is locked, so recent edits are not readable. "
            "Close Lightroom Classic before syncing.",
        )


async def check_immich(client: ImmichClient) -> list[CheckResult]:
    try:
        about = await client.server_about()
    except httpx.HTTPError as e:
        return [CheckResult("immich", False, str(e))]
    version = str(about.get("version", "")).lstrip("v")
    major = version.split(".")[0]
    if major.isdigit() and int(major) >= MIN_IMMICH_MAJOR:
        return [
            CheckResult("immich", True, "Reachable"),
            CheckResult("immich_version", True, f"Immich {version}"),
        ]
    return [
        CheckResult("immich", True, "Reachable"),
        CheckResult(
            "immich_version",
            False,
            f"Immich {version or 'unknown'} is older than "
            f"{MIN_IMMICH_MAJOR}.0; lrimmich targets the Immich v3 API",
        ),
    ]


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
        with closing(connect(catalog)) as conn:
            row = conn.execute(
                "SELECT af.pathFromRoot, lf.idx_filename "
                "FROM AgLibraryFile lf "
                "JOIN AgLibraryFolder af ON lf.folder = af.id_local "
                "LIMIT 1"
            ).fetchone()
        if not row:
            return CheckResult("path_mapping", False, "No files in catalog")
        relative_path = row["pathFromRoot"] + row["idx_filename"]
        tried: list[str] = []
        for lp in library_paths:
            expected = map_path(relative_path, lp, strip)
            tried.append(expected)
            expected_folder = expected.rsplit("/", 1)[0]
            assets = await client.get_folder_assets(expected_folder)
            for asset in assets:
                if asset.get("originalPath", "") == expected:
                    return CheckResult("path_mapping", True, f"Verified: {expected}")
        return CheckResult(
            "path_mapping",
            False,
            f"No asset found at {' or '.join(tried)} (from catalog {relative_path})",
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


async def run_doctor(cfg: Config, client: ImmichClient) -> DoctorReport:
    report = DoctorReport()
    report.checks.extend(await check_immich(client))
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
