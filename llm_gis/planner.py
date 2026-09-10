"""Which engine should run a job, and why.

Two engines serve this workspace and for some sources both of them work: a local
vector file can be read in place by DuckDB's ST_Read or ingested into PostGIS.
What separates them is whether the result has to outlive the command that made
it, and that is the only axis this module routes on. Size never branches a rule.

Nothing here opens a source. Format and locality come from the URI's suffix and
scheme, so the planner answers at discovery time, when the least is known.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from llm_gis.errors import UNSUPPORTED_FORMAT, GisError

PARQUET = "parquet"
VECTOR_FILE = "vector_file"
POSTGIS_TABLE = "postgis_table"
RASTER = "raster"

DUCKDB = "duckdb"
POSTGIS = "postgis"

LOCAL = "local"
REMOTE = "remote"

PARQUET_SUFFIXES = {".parquet", ".geoparquet", ".pq"}
VECTOR_SUFFIXES = {".gpkg", ".geojson", ".json", ".shp", ".fgb", ".kml", ".gml", ".gpx", ".csv"}
RASTER_SUFFIXES = {".tif", ".tiff", ".vrt"}
REMOTE_SCHEMES = ("http://", "https://", "s3://")

TABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

READERS = {
    PARQUET: [DUCKDB],
    VECTOR_FILE: [DUCKDB, POSTGIS],
    POSTGIS_TABLE: [POSTGIS],
    RASTER: [],
}


@dataclass(frozen=True)
class Source:
    """What a URI is, as far as its text alone can say."""

    uri: str
    format: str
    locality: str
    readers: list[str]


def readers(format_: str) -> list[str]:
    """Engines that can open this format. What can, not what should.

    The one authoritative format-to-engine table in this workspace.
    `catalog.readable_by` is a projection of it.
    """
    return list(READERS[format_])


def _suffix(uri: str) -> str:
    """The suffix, with any query string removed, as duck.reader_sql does."""
    return Path(uri.split("?")[0]).suffix.lower()


def _format(uri: str) -> str:
    if "/" not in uri and TABLE_PATTERN.match(uri):
        return POSTGIS_TABLE
    suffix = _suffix(uri)
    if suffix in PARQUET_SUFFIXES:
        return PARQUET
    if suffix in RASTER_SUFFIXES:
        return RASTER
    if suffix in VECTOR_SUFFIXES:
        return VECTOR_FILE
    raise GisError(
        UNSUPPORTED_FORMAT,
        f"Nothing in this workspace recognises {uri}",
        "Give a Parquet, GeoParquet, vector file, raster, or a schema.table name",
        {"suffix": suffix or None},
    )


def classify(uri: str) -> Source:
    """Format, locality and candidate engines, from the URI's text alone."""
    format_ = _format(uri)
    locality = REMOTE if uri.startswith(REMOTE_SCHEMES) else LOCAL
    return Source(uri=uri, format=format_, locality=locality, readers=readers(format_))
