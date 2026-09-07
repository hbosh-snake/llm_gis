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
from psycopg import sql

from llm_gis.common import (
    crs_text_from_ogr_coordinate_system,
    db_connect,
    normalize_crs,
    run_command,
)
from llm_gis.duck import _crs_from_geo_metadata, _geo_metadata, connect, reader_sql
from llm_gis.errors import COMMAND_FAILED, TABLE_NOT_FOUND, GisError

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


def _table_columns(cursor, schema: str, table: str) -> tuple[list[str], bool]:
    cursor.execute(
        """
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    rows = cursor.fetchall()
    if not rows:
        raise GisError(
            TABLE_NOT_FOUND,
            f"Table {schema}.{table} does not exist or is not visible to this role",
            "Run list-ingestions to see available schemas",
        )
    attributes = [name for name, udt in rows if udt not in {"geometry", "geography", "raster"}]
    is_raster = any(udt == "raster" for _, udt in rows)
    return attributes, is_raster


def _table_vector_metrics(cursor, schema: str, table: str, attributes: list[str], id_column: str | None) -> dict:
    relation = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    null_terms = sql.SQL(", ").join(
        sql.SQL("count(*) FILTER (WHERE {} IS NULL)").format(sql.Identifier(c)) for c in attributes
    )
    duplicate_term = (
        sql.SQL("count(*) - count(DISTINCT {})").format(sql.Identifier(id_column))
        if id_column
        else sql.SQL("NULL::bigint")
    )
    statement = sql.SQL(
        """
        SELECT count(*),
               count(*) FILTER (WHERE geom IS NULL OR ST_IsEmpty(geom)),
               count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)),
               ST_XMin(ST_Extent(geom)), ST_YMin(ST_Extent(geom)),
               ST_XMax(ST_Extent(geom)), ST_YMax(ST_Extent(geom)),
               max(ST_SRID(geom)),
               bool_or(ST_Zmflag(geom) IN (2, 3)),
               bool_or(ST_Zmflag(geom) IN (1, 3)),
               min(ST_Area(geom)), max(ST_Area(geom)), avg(ST_Area(geom)), sum(ST_Area(geom)),
               min(ST_Length(geom)), max(ST_Length(geom)), avg(ST_Length(geom)), sum(ST_Length(geom)),
               {duplicates}{null_head}{nulls}
        FROM {relation}
        """
    ).format(
        duplicates=duplicate_term,
        null_head=sql.SQL(", ") if attributes else sql.SQL(""),
        nulls=null_terms if attributes else sql.SQL(""),
        relation=relation,
    )
    cursor.execute(statement)
    values = cursor.fetchone()
    keys = [
        "feature_count", "empty_count", "invalid_count", "minx", "miny", "maxx", "maxy",
        "srid", "has_z", "has_m",
        "area_min", "area_max", "area_mean", "area_sum",
        "length_min", "length_max", "length_mean", "length_sum",
        "duplicate_id_count",
    ]
    row = dict(zip(keys, values))
    row["null_counts"] = {c: int(v) for c, v in zip(attributes, values[len(keys):])}
    return row


def _table_geometry_histogram(cursor, schema: str, table: str) -> dict[str, int]:
    cursor.execute(
        sql.SQL(
            "SELECT GeometryType(geom), count(*) FROM {}.{} WHERE geom IS NOT NULL GROUP BY 1"
        ).format(sql.Identifier(schema), sql.Identifier(table))
    )
    return {str(t): int(n) for t, n in cursor.fetchall()}


def _table_raster_metrics(cursor, schema: str, table: str) -> dict:
    """Structure only. Pixel statistics over a tiled raster table are deferred."""
    cursor.execute(
        """
        SELECT srid, scale_x, scale_y, num_bands,
               ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent)
        FROM raster_columns
        WHERE r_table_schema = %s AND r_table_name = %s
        """,
        (schema, table),
    )
    row = cursor.fetchone()
    if row is None:
        raise GisError(
            TABLE_NOT_FOUND,
            f"{schema}.{table} has a raster column but no raster_columns entry",
            "Re-run ingest-raster for this table",
        )
    srid, scale_x, scale_y, num_bands, minx, miny, maxx, maxy = row
    return {
        "crs": f"EPSG:{srid}" if srid else None,
        "bbox": None if minx is None else {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
        "vector": None,
        "raster": {
            "width": None,
            "height": None,
            "band_count": num_bands,
            "resolution": {"x": scale_x, "y": abs(scale_y) if scale_y else None},
            "bands": [],
            "stats_mode": "none",
        },
    }


def table_metrics(schema: str, table: str, id_column: str | None) -> tuple[dict, dict]:
    """Vector tables fully, raster tables structurally. Returns (source, metrics)."""
    with db_connect() as conn:
        with conn.cursor() as cursor:
            attributes, is_raster = _table_columns(cursor, schema, table)
            if is_raster:
                metrics = _table_raster_metrics(cursor, schema, table)
                kind = "raster"
            else:
                resolved_id = id_column or ("fid" if "fid" in attributes else None)
                row = _table_vector_metrics(cursor, schema, table, attributes, resolved_id)
                histogram = _table_geometry_histogram(cursor, schema, table)
                dimension = _dimension_stats(histogram)
                metrics = {
                    "crs": f"EPSG:{row['srid']}" if row["srid"] else None,
                    "bbox": None if row["minx"] is None else {
                        "minx": row["minx"], "miny": row["miny"],
                        "maxx": row["maxx"], "maxy": row["maxy"],
                    },
                    "vector": {
                        "feature_count": int(row["feature_count"]),
                        "geometry_types": histogram,
                        "declared_geometry_type": None,
                        "empty_count": int(row["empty_count"]),
                        "invalid_count": int(row["invalid_count"]),
                        "has_z": row["has_z"],
                        "has_m": row["has_m"],
                        "area_stats": _stats_block(row, "area") if dimension == "area" else None,
                        "length_stats": _stats_block(row, "length") if dimension == "length" else None,
                        "null_counts": row["null_counts"],
                        "duplicate_id_count": None if row["duplicate_id_count"] is None else int(row["duplicate_id_count"]),
                        "id_column": resolved_id,
                    },
                    "raster": None,
                }
                kind = "vector"
    return {"kind": "postgis_table", "ref": f"{schema}.{table}", "dataset_kind": kind}, metrics
