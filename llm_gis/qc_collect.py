"""All the I/O behind QC. One normalised metrics dict out, whatever the source.

Vector aggregates run in SQL rather than in memory, so QC over a large export
costs a scan, not a load. GDAL keeps authority over declared dimensionality,
which DuckDB's reader does not reliably preserve.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb

from llm_gis.common import (
    crs_text_from_ogr_coordinate_system,
    normalize_crs,
    run_command,
)
from llm_gis.duck import _crs_from_geo_metadata, _geo_metadata, connect, reader_sql
from llm_gis.errors import COMMAND_FAILED, GisError

RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}


def _ogr_layer(path: Path) -> dict[str, Any]:
    payload = json.loads(run_command(["ogrinfo", "-json", "-ro", str(path)]))
    return (payload.get("layers") or [{}])[0]


def _ogr_facts(path: Path) -> dict[str, Any]:
    """Declared CRS, geometry type and dimensionality, from GDAL's own reading."""
    layer = _ogr_layer(path)
    field = (layer.get("geometryFields") or [{}])[0]
    declared = field.get("type") or ""
    return {
        "crs": normalize_crs(crs_text_from_ogr_coordinate_system(field.get("coordinateSystem") or {})),
        "declared_geometry_type": declared or None,
        "has_z": "3D" in declared or declared.endswith("Z") or declared.endswith("ZM"),
        "has_m": "Measured" in declared or declared.endswith("M"),
    }


def _geometry_column(connection: duckdb.DuckDBPyConnection, reader: str, uri: str) -> str | None:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {reader}", [uri]).fetchall()
    for name, type_, *_ in rows:
        if str(type_).upper().startswith("GEOMETRY"):
            return name
    return None


def _columns(connection: duckdb.DuckDBPyConnection, reader: str, uri: str) -> list[str]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {reader}", [uri]).fetchall()
    return [name for name, *_ in rows]


def _dimension_stats(geometry_types: dict[str, int]) -> str:
    """Area for polygons, length for lines, neither for points."""
    dominant = max(geometry_types, key=geometry_types.get) if geometry_types else ""
    upper = dominant.upper()
    if "POLYGON" in upper:
        return "area"
    if "LINE" in upper:
        return "length"
    return "none"


def _vector_aggregates(
    connection: duckdb.DuckDBPyConnection,
    reader: str,
    uri: str,
    geometry: str,
    attributes: list[str],
    id_column: str | None,
) -> dict[str, Any]:
    g = f'"{geometry}"'
    null_terms = ", ".join(
        f'count(*) FILTER (WHERE "{c}" IS NULL) AS "null_{c}"' for c in attributes
    )
    duplicate_term = (
        f'count(*) - count(DISTINCT "{id_column}") AS duplicate_id_count'
        if id_column
        else "NULL AS duplicate_id_count"
    )
    statement = f"""
        SELECT count(*) AS feature_count,
               count(*) FILTER (WHERE {g} IS NULL OR ST_IsEmpty({g})) AS empty_count,
               count(*) FILTER (WHERE {g} IS NOT NULL AND NOT ST_IsValid({g})) AS invalid_count,
               min(ST_XMin({g})) AS minx, min(ST_YMin({g})) AS miny,
               max(ST_XMax({g})) AS maxx, max(ST_YMax({g})) AS maxy,
               min(ST_Area({g})) AS area_min, max(ST_Area({g})) AS area_max,
               avg(ST_Area({g})) AS area_mean, sum(ST_Area({g})) AS area_sum,
               min(ST_Length({g})) AS length_min, max(ST_Length({g})) AS length_max,
               avg(ST_Length({g})) AS length_mean, sum(ST_Length({g})) AS length_sum,
               {duplicate_term}
               {"," + null_terms if null_terms else ""}
        FROM {reader}
    """
    cursor = connection.execute(statement, [uri])
    names = [d[0] for d in cursor.description]
    return dict(zip(names, cursor.fetchone()))


def _geometry_histogram(
    connection: duckdb.DuckDBPyConnection, reader: str, uri: str, geometry: str
) -> dict[str, int]:
    rows = connection.execute(
        f'SELECT ST_GeometryType("{geometry}") AS t, count(*) FROM {reader} '
        f'WHERE "{geometry}" IS NOT NULL GROUP BY 1',
        [uri],
    ).fetchall()
    return {str(t): int(n) for t, n in rows}


def _stats_block(row: dict[str, Any], prefix: str) -> dict[str, float] | None:
    if row.get(f"{prefix}_sum") is None:
        return None
    return {
        "min": row[f"{prefix}_min"],
        "max": row[f"{prefix}_max"],
        "mean": row[f"{prefix}_mean"],
        "sum": row[f"{prefix}_sum"],
    }


def file_vector_metrics(path: Path, id_column: str | None) -> dict[str, Any]:
    uri = str(path)
    reader = reader_sql(uri)
    is_parquet = reader.startswith("read_parquet")
    connection = connect()
    try:
        geometry = _geometry_column(connection, reader, uri)
        if geometry is None:
            raise GisError(
                COMMAND_FAILED,
                f"No geometry column found in {uri}",
                "QC over a vector source needs a geometry column; use inspect for a plain table",
            )
        attributes = [c for c in _columns(connection, reader, uri) if c != geometry]
        row = _vector_aggregates(connection, reader, uri, geometry, attributes, id_column)
        histogram = _geometry_histogram(connection, reader, uri, geometry)
    except duckdb.Error as error:
        raise GisError(
            COMMAND_FAILED,
            f"DuckDB could not read {uri} for QC",
            "Confirm the file is a readable vector dataset or GeoParquet",
            {"duckdb_error": str(error)},
        ) from error

    if is_parquet:
        crs = _crs_from_geo_metadata(_geo_metadata(connection, uri))
        declared, has_z, has_m = None, None, None
    else:
        facts = _ogr_facts(path)
        crs = facts["crs"]
        declared, has_z, has_m = facts["declared_geometry_type"], facts["has_z"], facts["has_m"]

    dimension = _dimension_stats(histogram)
    bbox = (
        None
        if row["minx"] is None
        else {"minx": row["minx"], "miny": row["miny"], "maxx": row["maxx"], "maxy": row["maxy"]}
    )
    return {
        "crs": crs,
        "bbox": bbox,
        "vector": {
            "feature_count": int(row["feature_count"]),
            "geometry_types": histogram,
            "declared_geometry_type": declared,
            "empty_count": int(row["empty_count"]),
            "invalid_count": int(row["invalid_count"]),
            "has_z": has_z,
            "has_m": has_m,
            "area_stats": _stats_block(row, "area") if dimension == "area" else None,
            "length_stats": _stats_block(row, "length") if dimension == "length" else None,
            "null_counts": {c: int(row[f"null_{c}"]) for c in attributes},
            "duplicate_id_count": None if row["duplicate_id_count"] is None else int(row["duplicate_id_count"]),
            "id_column": id_column,
        },
        "raster": None,
    }


def file_raster_metrics(path: Path, exact_stats: bool) -> dict[str, Any]:
    """gdalinfo with PAM disabled: a .aux.xml write beside a read-only source would fail."""
    flag = "-stats" if exact_stats else "-approx_stats"
    env = {**os.environ, "GDAL_PAM_ENABLED": "NO"}
    payload = json.loads(run_command(["gdalinfo", "-json", flag, str(path)], env=env))
    size = payload.get("size") or [None, None]
    transform = payload.get("geoTransform") or [0, None, 0, 0, 0, None]
    corners = payload.get("cornerCoordinates", {})
    xs = [c[0] for c in corners.values() if c]
    ys = [c[1] for c in corners.values() if c]
    bands = []
    for band in payload.get("bands", []):
        metadata = (band.get("metadata") or {}).get("", {})
        valid_percent = metadata.get("STATISTICS_VALID_PERCENT")
        bands.append(
            {
                "index": band.get("band"),
                "nodata": band.get("noDataValue"),
                "min": band.get("minimum"),
                "max": band.get("maximum"),
                "mean": band.get("mean"),
                "percent_nodata": None if valid_percent is None else 100.0 - float(valid_percent),
            }
        )
    return {
        "crs": normalize_crs((payload.get("coordinateSystem") or {}).get("wkt")),
        "bbox": None if not xs else {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)},
        "vector": None,
        "raster": {
            "width": size[0],
            "height": size[1],
            "band_count": len(bands),
            "resolution": {"x": transform[1], "y": abs(transform[5]) if transform[5] else None},
            "bands": bands,
            "stats_mode": "exact" if exact_stats else "approximate",
        },
    }


def file_metrics(path: Path, id_column: str | None, exact_stats: bool) -> tuple[dict, dict]:
    """Dispatch on extension, then collect. Returns (source, metrics)."""
    kind = "raster" if path.suffix.lower() in RASTER_SUFFIXES else "vector"
    metrics = (
        file_raster_metrics(path, exact_stats)
        if kind == "raster"
        else file_vector_metrics(path, id_column)
    )
    return {"kind": "file", "ref": str(path), "dataset_kind": kind}, metrics
