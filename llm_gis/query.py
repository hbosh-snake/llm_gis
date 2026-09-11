"""Deterministic filters over a Parquet or GeoParquet source.

Higher-level than raw SQL on purpose: an agent asks for a bbox and an
attribute filter, and the SQL is built here. Raw SQL stays a separate,
explicitly privileged operation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from llm_gis.duck import connect, describe
from llm_gis.errors import COMMAND_FAILED, MISSING_ARGUMENT, UNSUPPORTED_FORMAT, GisError

OUTPUT_COPY_CLAUSE = {
    "parquet": "(FORMAT PARQUET)",
    "geopackage": "WITH (FORMAT GDAL, DRIVER 'GPKG')",
}


def _bbox_predicate(column: str, bbox: tuple[float, float, float, float]) -> str:
    minx, miny, maxx, maxy = bbox
    return (
        f'ST_Intersects("{column}", '
        f"ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy}))"
    )


def query(
    uri: str,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    where: str | None = None,
    columns: list[str] | None = None,
    limit: int | None = None,
    output_path: Path | None = None,
    output_format: str = "parquet",
) -> dict[str, Any]:
    """Filter a Parquet source, returning a summary or writing a subset.

    --bbox is in the source's own CRS (whatever describe(uri) reports as its
    crs), not lon/lat WGS84. This differs from catalog-search's --bbox,
    which is always WGS84. A bbox taken from catalog-search must be
    reprojected to the source CRS before it is handed to duck-query.

    --format geopackage writes an ingestible file instead of Parquet, through
    DuckDB's own bundled GDAL rather than the agent image's GDAL (which has
    no Parquet driver to read the source with in the first place). This is
    the conversion path bin/plan points to for a Parquet source that needs
    --materialise.
    """
    if output_format not in OUTPUT_COPY_CLAUSE:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"Unsupported duck-query output format: {output_format}",
            f"Use one of: {', '.join(OUTPUT_COPY_CLAUSE)}",
        )
    source = describe(uri)
    geometry_column = source["geometry_column"]

    if bbox and not geometry_column:
        raise GisError(
            MISSING_ARGUMENT,
            f"A bbox filter needs a geometry column, and {uri} has none",
            "Drop --bbox, or use a GeoParquet source",
        )

    selected = ", ".join(f'"{c}"' for c in columns) if columns else "*"
    predicates = [p for p in [_bbox_predicate(geometry_column, bbox) if bbox else None, where] if p]
    clause = f" WHERE {' AND '.join(predicates)}" if predicates else ""
    tail = f" LIMIT {int(limit)}" if limit else ""
    statement = f"SELECT {selected} FROM read_parquet(?){clause}{tail}"

    # GeoPackage assigns its own FID; a source "fid" column of the same name
    # otherwise conflicts with it in DuckDB's GDAL writer.
    write_selected = selected
    if output_format == "geopackage" and columns is None and any(c["name"] == "fid" for c in source["columns"]):
        write_selected = '* EXCLUDE ("fid")'
    write_statement = f"SELECT {write_selected} FROM read_parquet(?){clause}{tail}"

    connection = connect()
    try:
        matched = connection.execute(
            f"SELECT count(*) FROM ({statement})", [uri]
        ).fetchone()[0]
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            copy_clause = OUTPUT_COPY_CLAUSE[output_format]
            connection.execute(
                f"COPY ({write_statement}) TO '{output_path}' {copy_clause}", [uri]
            )
    except duckdb.Error as error:
        raise GisError(
            COMMAND_FAILED,
            f"DuckDB could not run the query against {uri}",
            "Check the --where expression and column names against duck-describe output",
            {"duckdb_error": str(error), "sql": statement},
        ) from error

    return {
        "uri": uri,
        "source_row_count": source["row_count"],
        "matched_row_count": matched,
        "crs": source["crs"],
        "bbox": list(bbox) if bbox else None,
        "where": where,
        "output_path": str(output_path) if output_path else None,
        "output_format": output_format,
        "engine": "duckdb",
    }
