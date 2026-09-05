from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from psycopg import sql

from llm_gis.common import (
    db_connect,
    ensure_workspace_dirs,
    make_ingest_id,
    parse_epsg,
    run_command,
    sanitize_identifier,
    sha256_for_path,
    utc_now,
    work_root,
    write_json,
)
from llm_gis.errors import CRS_MISSING, CRS_SUSPICIOUS, GisError
from llm_gis.inspect import inspect_dataset




def _loaded_dimensions(path: Path) -> tuple[int, list[int] | None]:
    """Band count and pixel size of the raster actually handed to raster2pgsql."""
    payload = json.loads(run_command(["gdalinfo", "-json", str(path)]))
    return len(payload.get("bands", [])), payload.get("size")


def ingest_raster(
    input_path: Path,
    table: str,
    ingest_id: str | None,
    src_crs: str | None,
    dst_crs: str | None,
    schema: str | None,
) -> dict[str, Any]:
    ensure_workspace_dirs()
    input_hash = sha256_for_path(input_path)
    resolved_ingest_id = ingest_id or make_ingest_id(input_hash)
    resolved_schema = sanitize_identifier(schema or f"raw_{resolved_ingest_id}")
    resolved_table = sanitize_identifier(table)

    inspect_report = inspect_dataset(input_path)
    crs_status = inspect_report.get("crs_status")
    detected_crs = inspect_report.get("detected_crs")
    if crs_status in {"missing", "suspicious"} and not src_crs:
        code = CRS_MISSING if crs_status == "missing" else CRS_SUSPICIOUS
        raise GisError(
            code,
            f"Raster ingestion refused: CRS is {crs_status} for {input_path}",
            "Provide --src-crs with the dataset's true CRS and retry",
        )

    raster_input = input_path
    if dst_crs:
        warped = work_root() / "staging" / resolved_ingest_id / "warped.tif"
        warped.parent.mkdir(parents=True, exist_ok=True)
        warp_cmd = ["gdalwarp"]
        if src_crs:
            warp_cmd.extend(["-s_srs", src_crs])
        warp_cmd.extend(["-t_srs", dst_crs, str(input_path), str(warped)])
        run_command(warp_cmd)
        raster_input = warped

    chosen_crs = dst_crs or src_crs or detected_crs
    srid = parse_epsg(chosen_crs if isinstance(chosen_crs, str) else None)
    band_count, size = _loaded_dimensions(raster_input)

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {};").format(sql.Identifier(resolved_schema)))

    srid_part = f"-s {srid}" if srid else ""
    shell_cmd = (
        f"raster2pgsql {srid_part} -I -C -M {shlex.quote(str(raster_input))} "
        f"{shlex.quote(resolved_schema + '.' + resolved_table)} | psql -v ON_ERROR_STOP=1"
    )
    run_command(["bash", "-lc", shell_cmd], env=os.environ.copy())

    details = {
        "dataset_kind": "raster",
        "schema": resolved_schema,
        "table": resolved_table,
        "crs_status": crs_status,
        "srid": srid,
    }
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO meta.ingestions (ingest_id, input_path, input_hash, detected_crs, chosen_crs, status, report_path, log_dir, details)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                ON CONFLICT (ingest_id) DO UPDATE SET
                    input_path=EXCLUDED.input_path,
                    input_hash=EXCLUDED.input_hash,
                    detected_crs=EXCLUDED.detected_crs,
                    chosen_crs=EXCLUDED.chosen_crs,
                    status=EXCLUDED.status,
                    report_path=EXCLUDED.report_path,
                    log_dir=EXCLUDED.log_dir,
                    details=EXCLUDED.details,
                    updated_at=now();
                """,
                (
                    resolved_ingest_id,
                    str(input_path),
                    input_hash,
                    str(detected_crs) if detected_crs else None,
                    str(chosen_crs) if chosen_crs else None,
                    "success",
                    str(work_root() / "reports" / f"{resolved_ingest_id}.json"),
                    str(work_root() / "logs" / resolved_ingest_id),
                    json.dumps(details),
                ),
            )

    report = {
        "ingest_id": resolved_ingest_id,
        "input_path": str(input_path),
        "input_hash": input_hash,
        "dataset_kind": "raster",
        "schema": resolved_schema,
        "table": resolved_table,
        "detected_crs": detected_crs,
        "chosen_crs": chosen_crs,
        "crs_status": crs_status,
        "band_count": band_count,
        "size": size,
        "created_at": utc_now(),
    }
    write_json(work_root() / "reports" / f"{resolved_ingest_id}.json", report)
    return report
