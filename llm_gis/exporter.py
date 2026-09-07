from __future__ import annotations

import json
from pathlib import Path

from llm_gis.common import crs_text_from_ogr_coordinate_system, ensure_workspace_dirs, pg_gdal_dsn, run_command, work_root
from llm_gis.duck import connect as duck_connect, describe as duck_describe
from llm_gis.errors import MISSING_ARGUMENT, UNSUPPORTED_FORMAT, GisError
from llm_gis.qc import QcContext, qc_report, reference_for


def _written_vector_summary(path: Path) -> tuple[int | None, str | None]:
    """Feature count and CRS actually present in the file just written."""
    try:
        payload = json.loads(run_command(["ogrinfo", "-json", "-ro", str(path)]))
    except GisError:
        return None, None
    layers = payload.get("layers") or [{}]
    layer = layers[0]
    fields = layer.get("geometryFields") or []
    crs_text = crs_text_from_ogr_coordinate_system(fields[0].get("coordinateSystem") or {}) if fields else None
    return layer.get("featureCount"), crs_text


def _to_geoparquet(source: Path, destination: Path) -> None:
    """Convert a written GeoPackage to GeoParquet through DuckDB's spatial reader."""
    connection = duck_connect()
    connection.execute(
        f"COPY (SELECT * FROM ST_Read('{source}')) TO '{destination}' (FORMAT PARQUET)"
    )


def _export_reference(table: str | None, compare_to: str | None) -> dict | None:
    """--compare-to, else the source table, else nothing.

    A --table export compared against its own table is close to a tautology:
    it catches a reprojection or driver fault and nothing else. A --sql export
    has no inferable input, which is why --compare-to exists.
    """
    if compare_to:
        return reference_for(compare_to)
    if table:
        return reference_for(table)
    return None


def export_result(
    output_path: Path,
    output_format: str,
    *,
    table: str | None = None,
    sql_query: str | None = None,
    qc: bool = True,
    compare_to: str | None = None,
) -> dict:
    ensure_workspace_dirs()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not table and not sql_query:
        raise GisError(
            MISSING_ARGUMENT,
            "Export requires either a table or a SQL query",
            "Pass --table or --sql",
        )

    fmt = output_format.lower()
    if fmt == "gpkg":
        gdal_format = "GPKG"
    elif fmt == "geojson":
        gdal_format = "GeoJSON"
    elif fmt in {"parquet", "geoparquet"}:
        gdal_format = "GPKG"  # written first, then converted; see _to_geoparquet
    else:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"Unsupported export format: {output_format}",
            "Use --format gpkg, geojson or parquet",
        )

    # This GDAL build has no Parquet driver, so DuckDB converts a temporary
    # GeoPackage rather than adding a heavy Arrow dependency for one format.
    wants_parquet = fmt in {"parquet", "geoparquet"}
    written_path = (
        work_root() / "tmp" / f"{output_path.stem}.export.gpkg" if wants_parquet else output_path
    )
    cmd = ["ogr2ogr", "-f", gdal_format, str(written_path), pg_gdal_dsn()]
    if sql_query:
        cmd.extend(["-sql", sql_query])
    elif table:
        cmd.append(table)

    run_command(cmd)

    if wants_parquet:
        _to_geoparquet(written_path, output_path)
        written_path.unlink(missing_ok=True)
    if wants_parquet:
        written = duck_describe(str(output_path))
        feature_count, crs = written["row_count"], written["crs"]
    else:
        feature_count, crs = _written_vector_summary(output_path)
    result = {
        "output_path": str(output_path),
        "output_format": fmt,
        "table": table,
        "sql": sql_query,
        "feature_count": feature_count,
        "crs": crs,
    }
    if qc:
        result["qc"] = qc_report(str(output_path), QcContext(reference=_export_reference(table, compare_to)))
    return result
