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
    raise FileNotFoundError(path)


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
        raise ValueError(f"Path {path} is outside allowed root {root}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


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
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {command}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
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


def parse_epsg(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"EPSG[:=](\d+)", value.upper())
    if match:
        return int(match.group(1))
    return None


def crs_status(crs_text: str | None, extent: dict[str, float] | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not crs_text:
        return "missing", ["No CRS detected"]
    if extent is None:
        return "ok", reasons

    minx = extent.get("minx")
    maxx = extent.get("maxx")
    miny = extent.get("miny")
    maxy = extent.get("maxy")

    crs_upper = crs_text.upper()
    epsg = parse_epsg(crs_text)
    if epsg == 4326:
        if any(abs(v) > 180 for v in [minx or 0.0, maxx or 0.0]) or any(abs(v) > 90 for v in [miny or 0.0, maxy or 0.0]):
            reasons.append("Extent exceeds lon/lat ranges for EPSG:4326")
    if epsg == 3857 or (epsg is not None and 32600 <= epsg <= 32799) or any(token in crs_upper for token in ["UTM", "METER", "METRE"]):
        if all(-180 <= v <= 180 for v in [minx or 0.0, maxx or 0.0]) and all(-90 <= v <= 90 for v in [miny or 0.0, maxy or 0.0]):
            reasons.append("Projected CRS appears to have lon/lat-like extent")

    return ("suspicious", reasons) if reasons else ("ok", reasons)


def ensure_workspace_dirs() -> None:
    for path in [Path("/data/work/tmp"), Path("/data/work/logs"), Path("/data/work/reports"), Path("/data/work/staging")]:
        path.mkdir(parents=True, exist_ok=True)


def safe_remove_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
