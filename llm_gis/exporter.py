from __future__ import annotations

from pathlib import Path

from llm_gis.common import ensure_workspace_dirs, pg_gdal_dsn, run_command
from llm_gis.errors import MISSING_ARGUMENT, UNSUPPORTED_FORMAT, GisError


def export_result(
    output_path: Path,
    output_format: str,
    *,
    table: str | None = None,
    sql_query: str | None = None,
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
    else:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"Unsupported export format: {output_format}",
            "Use --format gpkg or --format geojson",
        )

    cmd = ["ogr2ogr", "-f", gdal_format, str(output_path), pg_gdal_dsn()]
    if sql_query:
        cmd.extend(["-sql", sql_query])
    elif table:
        cmd.append(table)

    run_command(cmd)
    return {
        "output_path": str(output_path),
        "output_format": fmt,
        "table": table,
        "sql": sql_query,
    }
