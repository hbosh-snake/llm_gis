from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from pyproj import CRS
from pyproj.exceptions import CRSError

from llm_gis.errors import COMMAND_FAILED, INPUT_NOT_FOUND, PATH_OUTSIDE_ROOT, GisError


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_identifier(value: str) -> str:
    lowered = value.lower()
    cleaned = re.sub(r"[^a-z0-9_]+", "_", lowered).strip("_")
    if not cleaned:
        raise ValueError("Identifier is empty after sanitization")
    return cleaned


def sha256_for_path(path: Path) -> str:
    if path.is_file():
        return _sha256_for_file(path)
    if path.is_dir():
        digest = hashlib.sha256()
        for item in sorted(path.rglob("*")):
            if item.is_file():
                rel = item.relative_to(path)
                digest.update(str(rel).encode("utf-8"))
                digest.update(_sha256_for_file(item).encode("ascii"))
        return digest.hexdigest()
    raise GisError(
        INPUT_NOT_FOUND,
        f"Input path does not exist: {path}",
        "Check the path; inputs are read from inside the container, usually under /data/incoming",
    )


def _sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def make_ingest_id(source_hash: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{stamp}_{source_hash[:10]}"


def ensure_child_path(path: Path, root: Path) -> None:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise GisError(
            PATH_OUTSIDE_ROOT,
            f"Path {path} is outside allowed root {root}",
            f"Use a path under {root}",
        )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _redact(text: str) -> str:
    """Strip credentials from anything that reaches machine-readable output."""
    text = re.sub(r"(password=)[^\s'\"]+", r"\1***", text)
    return re.sub(r"(://[^:/\s]+:)[^@\s]+(@)", r"\1***\2", text)


def run_command(
    args: list[str] | str,
    *,
    input_text: str | None = None,
    shell: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        args,
        check=False,
        text=True,
        capture_output=True,
        input=input_text,
        shell=shell,
        env=env,
    )
    if completed.returncode != 0:
        command = args if isinstance(args, str) else " ".join(shlex.quote(arg) for arg in args)
        redacted = _redact(command)
        raise GisError(
            COMMAND_FAILED,
            f"Command failed with exit {completed.returncode}: {redacted}",
            "Read details.stderr for the underlying tool diagnostic",
            {
                "command": redacted,
                "returncode": completed.returncode,
                "stderr": _redact(completed.stderr[-2000:]),
                "stdout": _redact(completed.stdout[-2000:]),
            },
        )
    return completed.stdout


def pg_dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if dsn:
        return dsn
    host = os.getenv("PGHOST", "db")
    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE", "gis")
    user = os.getenv("PGUSER", "gis")
    password = os.getenv("PGPASSWORD", "gis")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def pg_gdal_dsn() -> str:
    host = os.getenv("PGHOST", "db")
    port = os.getenv("PGPORT", "5432")
    database = os.getenv("PGDATABASE", "gis")
    user = os.getenv("PGUSER", "gis")
    password = os.getenv("PGPASSWORD", "gis")
    return f"PG:host={host} port={port} dbname={database} user={user} password={password}"


def db_connect() -> psycopg.Connection:
    return psycopg.connect(pg_dsn())


def parse_crs(value: str | None) -> CRS | None:
    """Parse an EPSG code, WKT or PROJ string. None if absent or unparseable."""
    if not value:
        return None
    try:
        return CRS.from_user_input(value)
    except CRSError:
        return None


def parse_epsg(value: str | None) -> int | None:
    crs = parse_crs(value)
    return crs.to_epsg() if crs else None


def crs_text_from_ogr_coordinate_system(coordinate_system: dict[str, Any]) -> str | None:
    """Extract 'AUTHORITY:CODE', falling back to WKT, from an ogrinfo/gdalinfo coordinateSystem block."""
    projjson_id = (coordinate_system.get("projjson") or {}).get("id") or {}
    authority = projjson_id.get("authority")
    code = projjson_id.get("code")
    if authority and code:
        return f"{authority}:{code}"
    return coordinate_system.get("wkt")


def crs_status(crs_text: str | None, extent: dict[str, float] | None) -> tuple[str, list[str]]:
    """Classify a CRS as ok, missing or suspicious given the dataset extent."""
    if not crs_text:
        return "missing", ["No CRS detected"]

    crs = parse_crs(crs_text)
    if crs is None:
        return "suspicious", ["CRS could not be parsed"]
    if extent is None:
        return "ok", []

    reasons: list[str] = []
    lon_lat_like = (
        -180 <= extent["minx"] <= 180
        and -180 <= extent["maxx"] <= 180
        and -90 <= extent["miny"] <= 90
        and -90 <= extent["maxy"] <= 90
    )
    if crs.is_geographic and not lon_lat_like:
        reasons.append("Geographic CRS but extent exceeds lon/lat ranges")
    if crs.is_projected and lon_lat_like:
        reasons.append("Projected CRS appears to have lon/lat-like extent")

    return ("suspicious", reasons) if reasons else ("ok", reasons)


def incoming_root() -> Path:
    """Read-only source root, overridable for testing."""
    return Path(os.getenv("LLM_GIS_INCOMING_ROOT", "/data/incoming"))


def work_root() -> Path:
    """Workspace root, overridable for host-side testing."""
    return Path(os.getenv("LLM_GIS_WORK_ROOT", "/data/work"))


def ensure_workspace_dirs() -> None:
    root = work_root()
    for name in ["tmp", "logs", "reports", "staging"]:
        (root / name).mkdir(parents=True, exist_ok=True)


def safe_remove_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
