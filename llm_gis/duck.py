"""DuckDB execution path for Parquet and GeoParquet, local or remote.

Deliberately separate from the PostGIS path: DuckDB answers cheap questions
about a dataset without materialising it, PostGIS owns persistent workspaces.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import duckdb

from llm_gis.asset import LOCAL_FILE, REMOTE_URI, Asset, Column, Provenance
from llm_gis.common import normalize_crs
from llm_gis.errors import COMMAND_FAILED, GisError

EXTENSIONS = ("spatial", "httpfs")


def connect() -> duckdb.DuckDBPyConnection:
    """An in-memory connection with the spatial and httpfs extensions loaded."""
    connection = duckdb.connect()
    extension_dir = os.getenv("LLM_GIS_DUCKDB_EXTENSION_DIR")
    if extension_dir:
        Path(extension_dir).mkdir(parents=True, exist_ok=True)
        connection.execute(f"SET extension_directory = '{extension_dir}';")
    for extension in EXTENSIONS:
        connection.execute(f"INSTALL {extension}; LOAD {extension};")
    return connection


def _scalar(connection: duckdb.DuckDBPyConnection, sql: str, uri: str) -> Any:
    return connection.execute(sql, [uri]).fetchone()[0]


def describe(uri: str) -> dict[str, Any]:
    """Schema, row count and spatial extent of a Parquet or GeoParquet source."""
    connection = connect()
    try:
        columns = [
            Column(name, type_)
            for name, type_ in connection.execute(
                "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))", [uri]
            ).fetchall()
        ]
        row_count = _scalar(connection, "SELECT count(*) FROM read_parquet(?)", uri)
    except duckdb.Error as error:
        raise GisError(
            COMMAND_FAILED,
            f"DuckDB could not read {uri}",
            "Confirm the URI is a readable Parquet or GeoParquet file; remote URIs need https or s3",
            {"duckdb_error": str(error)},
        ) from error

    meta = _geo_metadata(connection, uri)
    geometry = next((c for c in columns if c.type.upper().startswith("GEOMETRY")), None)
    bbox = _bbox(connection, uri, geometry.name) if geometry else None
    crs = _crs_from_type(geometry.type) if geometry else None
    if crs is None and meta:
        crs = _crs_from_geo_metadata(meta)

    return _to_describe(
        _build_asset(uri, columns, row_count, geometry.name if geometry else None, bbox, crs)
    )


def _build_asset(
    uri: str,
    columns: list[Column],
    row_count: int,
    geometry_column: str | None,
    bbox: dict[str, float] | None,
    crs: str | None,
) -> Asset:
    """What DuckDB measured, as an Asset. Everything here was read, not advertised."""
    source_type = REMOTE_URI if uri.startswith(("http://", "https://", "s3://")) else LOCAL_FILE
    return Asset(
        uri=uri,
        provenance=Provenance(source_type),
        crs=crs,
        bbox=bbox,
        record_count=row_count,
        geometry_column=geometry_column,
        columns=columns,
    )


def _to_describe(asset: Asset) -> dict[str, Any]:
    """The historic duck-describe keys, unchanged."""
    return {
        "uri": asset.uri,
        "row_count": asset.record_count,
        "columns": [{"name": c.name, "type": c.type} for c in asset.columns],
        "geometry_column": asset.geometry_column,
        "crs": asset.crs,
        "bbox": asset.bbox,
    }


def _crs_from_type(type_text: str) -> str | None:
    """DuckDB spells a GeoParquet geometry column as GEOMETRY('EPSG:4326')."""
    match = re.search(r"'([^']+)'", type_text)
    return normalize_crs(match.group(1)) if match else None


def _geo_metadata(connection: duckdb.DuckDBPyConnection, uri: str) -> dict[str, Any]:
    """The GeoParquet 'geo' key, where the spec puts the CRS and primary column."""
    rows = connection.execute("SELECT key, value FROM parquet_kv_metadata(?)", [uri]).fetchall()
    for key, value in rows:
        if _text(key) == "geo":
            return json.loads(_text(value))
    return {}


def _text(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


def _crs_from_geo_metadata(meta: dict[str, Any]) -> str | None:
    column = meta.get("columns", {}).get(meta.get("primary_column"), {})
    crs = column.get("crs")
    if crs is None:
        return "EPSG:4326"  # the spec's default when the key is absent
    return normalize_crs(json.dumps(crs) if isinstance(crs, dict) else str(crs))


def _bbox(connection: duckdb.DuckDBPyConnection, uri: str, column: str) -> dict[str, float] | None:
    row = connection.execute(
        f'SELECT min(ST_XMin("{column}")), min(ST_YMin("{column}")), '
        f'max(ST_XMax("{column}")), max(ST_YMax("{column}")) FROM read_parquet(?)',
        [uri],
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return {"minx": row[0], "miny": row[1], "maxx": row[2], "maxy": row[3]}


PARQUET_SUFFIXES = {".parquet", ".geoparquet", ".pq"}


def reader_sql(uri: str) -> str:
    """The table function that reads this source, chosen by extension.

    The agent GDAL build has no Parquet driver, so ST_Read cannot open a
    Parquet file at all; read_parquet cannot open a GeoPackage. One of the
    two is always right and the extension says which.
    """
    suffix = Path(uri.split("?")[0]).suffix.lower()
    return "read_parquet(?)" if suffix in PARQUET_SUFFIXES else "ST_Read(?)"
