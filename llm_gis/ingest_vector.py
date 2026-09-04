from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from psycopg import sql

from llm_gis.common import (
    db_connect,
    ensure_workspace_dirs,
    make_ingest_id,
    pg_gdal_dsn,
    run_command,
    sanitize_identifier,
    sha256_for_path,
    utc_now,
    work_root,
    write_json,
)
from llm_gis.errors import CRS_MISSING, CRS_SUSPICIOUS, GisError
from llm_gis.inspect import inspect_dataset




def _ogr_command(
    input_path: Path,
    schema: str,
    table: str,
    src_crs: str | None,
    dst_crs: str | None,
    dsn: str,
) -> list[str]:
    command = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        dsn,
        str(input_path),
        "-nln",
        f"{schema}.{table}",
        "-nlt",
        "PROMOTE_TO_MULTI",
        "-lco",
        "GEOMETRY_NAME=geom",
        "-lco",
        "FID=fid",
        "-overwrite",
    ]
    if src_crs:
        command.extend(["-s_srs", src_crs])
    if dst_crs:
        command.extend(["-t_srs", dst_crs])
    return command


def ingest_vector(
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
            f"Vector ingestion refused: CRS is {crs_status} for {input_path}",
            "Provide --src-crs with the dataset's true CRS and retry",
        )
    chosen_crs = dst_crs or src_crs or detected_crs

    ogr_cmd = _ogr_command(
        input_path=input_path,
        schema=resolved_schema,
        table=resolved_table,
        src_crs=src_crs,
        dst_crs=dst_crs,
        dsn=pg_gdal_dsn(),
    )

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {};").format(sql.Identifier(resolved_schema)))

    run_command(ogr_cmd)

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name='geom');"
                ),
                (resolved_schema, resolved_table),
            )
            has_geom = bool(cur.fetchone()[0])
            invalid_before = 0
            invalid_after = 0
            if has_geom:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{} WHERE geom IS NOT NULL AND NOT ST_IsValid(geom);").format(
                        sql.Identifier(resolved_schema), sql.Identifier(resolved_table)
                    )
                )
                invalid_before = int(cur.fetchone()[0])
                cur.execute(
                    sql.SQL("UPDATE {}.{} SET geom = ST_Force2D(ST_MakeValid(geom)) WHERE geom IS NOT NULL AND NOT ST_IsValid(geom);").format(
                        sql.Identifier(resolved_schema), sql.Identifier(resolved_table)
                    )
                )
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{} WHERE geom IS NOT NULL AND NOT ST_IsValid(geom);").format(
                        sql.Identifier(resolved_schema), sql.Identifier(resolved_table)
                    )
                )
                invalid_after = int(cur.fetchone()[0])
                cur.execute(
                    sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {}.{} USING GIST (geom);").format(
                        sql.Identifier(f"{resolved_table}_geom_gix"),
                        sql.Identifier(resolved_schema),
                        sql.Identifier(resolved_table),
                    )
                )

            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {}.{};").format(
                    sql.Identifier(resolved_schema), sql.Identifier(resolved_table)
                )
            )
            feature_count = int(cur.fetchone()[0])

            details = {
                "dataset_kind": "vector",
                "schema": resolved_schema,
                "table": resolved_table,
                "invalid_before": invalid_before,
                "invalid_after": invalid_after,
                "crs_status": crs_status,
            }
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
        "dataset_kind": "vector",
        "schema": resolved_schema,
        "table": resolved_table,
        "detected_crs": detected_crs,
        "chosen_crs": chosen_crs,
        "crs_status": crs_status,
        "feature_count": feature_count,
        "invalid_before": invalid_before,
        "invalid_after": invalid_after,
        "created_at": utc_now(),
    }
    write_json(work_root() / "reports" / f"{resolved_ingest_id}.json", report)
    return report
