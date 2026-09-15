from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError

from llm_gis.errors import (
    COMMAND_FAILED,
    INPUT_NOT_FOUND,
    PATH_OUTSIDE_ROOT,
    REMOTE_READ_FAILED,
    GisError,
)


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
    return f"{stamp}_{source_hash[:10]}_{secrets.token_hex(3)}"


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


REMOTE_SCHEMES = ("http://", "https://", "s3://")


def is_remote(uri: str) -> bool:
    """Whether this source lives behind a network scheme rather than on disk.

    `planner.py` states the same tuple and deliberately does not import it: the
    planner stays free of this module's psycopg and pyproj imports so its whole
    test suite runs with no database.
    """
    return str(uri).startswith(REMOTE_SCHEMES)


def gdal_uri(uri: str) -> str:
    """A source as GDAL must be handed it: the VSI convention, stated once.

    Every GDAL invocation in this workspace goes through here, so a remote read
    is a range request rather than a download without any call site saying so.
    """
    text = str(uri)
    if text.startswith(("http://", "https://")):
        return f"/vsicurl/{text}"
    if text.startswith("s3://"):
        return f"/vsis3/{text[len('s3://'):]}"
    return text


def remote_read_error(uri: str, error: GisError) -> GisError:
    """A failed range request, named as one.

    GDAL reports an HTTP failure as a generic non-zero exit, which reads like a
    malformed file. Pulling the status out means a 403 on a requester-pays bucket
    suggests credentials rather than a corrupt raster.
    """
    stderr = str(error.details.get("stderr", ""))
    match = re.search(r"HTTP response code:\s*(\d{3})", stderr)
    status = int(match.group(1)) if match else None
    return GisError(
        REMOTE_READ_FAILED,
        f"Could not read {uri} over HTTP",
        "Check the URI, and whether the bucket needs credentials or is requester-pays",
        {"uri": uri, "http_status": status, "stderr": stderr[-500:]},
    )


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


def normalize_crs(crs_text: str | None) -> str | None:
    """Reduce a CRS to a compact authority:code, whatever form it arrived in.

    WKT, PROJJSON and EPSG strings all collapse to the same shape. OGC:CRS84 has
    no EPSG code but is not EPSG:4326 either, since its axis order differs, so it
    keeps its own authority rather than being coerced.
    """
    crs = parse_crs(crs_text)
    if crs is None:
        return crs_text
    epsg = crs.to_epsg()
    if epsg:
        return f"EPSG:{epsg}"
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs_text


def reproject_bbox(
    bbox: dict[str, float] | None, src_crs: str | None, dst_crs: str | None
) -> dict[str, float] | None:
    """Transform a bbox, densifying the edges so a curved edge is not clipped off.

    Shared by QC's disjointness check and by the raster reader, which reports every
    window in its native CRS and in 4326 so a caller can compare the two.
    """
    if bbox is None or not src_crs or not dst_crs or src_crs == dst_crs:
        return bbox
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    minx, miny, maxx, maxy = transformer.transform_bounds(
        bbox["minx"], bbox["miny"], bbox["maxx"], bbox["maxy"]
    )
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


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


def allowed_source_roots() -> tuple[Path, ...]:
    """Return the resolved roots from which local source paths may be read."""
    configured = [incoming_root(), *(
        Path(value)
        for value in os.getenv("LLM_GIS_SOURCE_ROOTS", "").split(os.pathsep)
        if value
    )]
    roots: list[Path] = []
    for root in configured:
        resolved = root.resolve()
        if resolved == Path("/"):
            raise GisError(
                PATH_OUTSIDE_ROOT,
                "Filesystem root is not an allowed source root",
                "Set LLM_GIS_SOURCE_ROOTS to one or more specific source directories",
            )
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def ensure_source_path(path: Path) -> None:
    """Ensure a local source is contained by one of the configured roots."""
    resolved = path.resolve()
    roots = allowed_source_roots()
    if any(resolved == root or root in resolved.parents for root in roots):
        return
    roots_text = ", ".join(str(root) for root in roots)
    raise GisError(
        PATH_OUTSIDE_ROOT,
        f"Path {path} is outside allowed source roots",
        f"Use a path under one of: {roots_text}",
    )


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
