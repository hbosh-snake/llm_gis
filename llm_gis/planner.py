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
from dataclasses import dataclass, field
from pathlib import Path

from llm_gis.errors import MISSING_ARGUMENT, UNSUPPORTED_FORMAT, GisError

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


QUERY = "query"
ANALYSE = "analyse"
EXPORT = "export"
OPERATIONS = (QUERY, ANALYSE, EXPORT)

NO_CONVERSION_PATH = "NO_CONVERSION_PATH"
REMOTE_UNINDEXED_READ = "REMOTE_UNINDEXED_READ"

BLOCKED_PARQUET = {
    "code": NO_CONVERSION_PATH,
    "message": (
        "Nothing here writes a GDAL-readable file from a Parquet source: GDAL in this "
        "image has no Parquet driver, and duck-query --output writes Parquet."
    ),
    "suggested_action": (
        "Query in place without --materialise, or add a GPKG output format to duck-query "
        "(DuckDB supports COPY ... FORMAT GDAL)."
    ),
}


@dataclass
class Route:
    """One routing decision, with the argument for it."""

    strategy: str | None
    reason: str
    fallback: dict | None = None
    overridden: str | None = None
    warnings: list[dict] = field(default_factory=list)
    blocked_by: dict | None = None


def _blocked(reason: str) -> Route:
    return Route(strategy=None, reason=reason, blocked_by=dict(BLOCKED_PARQUET))


def _refuse_override(source: Source, engine: str) -> None:
    """An override the source cannot honour fails loudly rather than routing around it."""
    if engine not in source.readers:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"{engine} cannot open {source.uri}",
            f"Drop --engine, or use one of: {', '.join(source.readers) or 'no engine here'}",
            {"requested_engine": engine, "readers": source.readers},
        )


def _query_route(source: Source, materialise: bool) -> Route:
    if source.format == POSTGIS_TABLE:
        return Route(POSTGIS, "the table is already in the workspace")
    if source.format == PARQUET:
        if materialise:
            return _blocked("a Parquet source cannot reach the workspace today")
        return Route(DUCKDB, "DuckDB reads Parquet in place; no database is needed")
    if materialise:
        return Route(
            POSTGIS,
            "the result must survive this command, and the workspace is where results live",
            fallback={"strategy": DUCKDB, "requires": None, "loses": "persistence"},
        )
    warnings = []
    if source.locality == REMOTE:
        warnings.append(
            {
                "code": REMOTE_UNINDEXED_READ,
                "message": "A remote non-Parquet vector file is read whole and unindexed over HTTP",
                "severity": "warning",
            }
        )
    return Route(
        DUCKDB,
        "ST_Read opens a vector file without ingesting it, and no persistence was requested",
        fallback={"strategy": POSTGIS, "requires": "stage and ingest-vector first", "loses": None},
        warnings=warnings,
    )


def _analyse_route(source: Source) -> Route:
    if source.format == PARQUET:
        return _blocked("SQL across sources runs in the workspace, which Parquet cannot reach today")
    return Route(POSTGIS, "SQL across sources needs the persistent workspace")


def _export_route(source: Source) -> Route:
    if source.format == POSTGIS_TABLE:
        return Route(POSTGIS, "bin/export writes from the workspace")
    return Route(DUCKDB, "the source never enters the database")


def route(
    operation: str,
    source: Source,
    *,
    materialise: bool = False,
    engine: str | None = None,
) -> Route:
    """Which engine runs this operation on this source, and the argument for it."""
    if operation not in OPERATIONS:
        raise GisError(
            MISSING_ARGUMENT,
            f"Unknown operation: {operation}",
            f"Use one of: {', '.join(OPERATIONS)}",
        )
    if not source.readers:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"No engine here can open {source.uri}",
            "Cloud raster arrives in Phase 7; ingest-raster still loads a local raster",
            {"format": source.format},
        )

    if engine is not None:
        if engine == POSTGIS and source.format == PARQUET:
            return _blocked("a Parquet source cannot reach the workspace today")
        _refuse_override(source, engine)

    if operation == QUERY:
        decided = _query_route(source, materialise)
    elif operation == ANALYSE:
        decided = _analyse_route(source)
    else:
        decided = _export_route(source)

    if engine is not None and decided.strategy != engine:
        return Route(
            engine,
            f"requested with --engine {engine}, overriding: {decided.reason}",
            fallback={"strategy": decided.strategy, "requires": None, "loses": None},
            overridden="engine",
            warnings=decided.warnings,
        )
    if engine is not None:
        decided.overridden = "engine"
    return decided


@dataclass
class Step:
    """One bin/* invocation, with the reason it is in the list."""

    command: str
    argv: list[str]
    why: str


def _ingest_id(uri: str) -> str:
    """A deterministic id from the file name, so stage and ingest-vector agree.

    stage invents a timestamped id when it is not given one, which would make every
    later step in a printed plan unpasteable.
    """
    stem = Path(uri.split("?")[0]).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_")


def _flags(**pairs: str | None) -> list[str]:
    """Only the flags the caller actually supplied, in the order given."""
    argv = []
    for name, value in pairs.items():
        if value is not None:
            argv += [f"--{name.replace('_', '-')}", value]
    return argv


def _postgis_predicate(bbox: str | None, where: str | None) -> str:
    """The filter as SQL. ST_SRID(geom) keeps it correct without reading the file."""
    parts = []
    if bbox:
        parts.append(f"ST_Intersects(geom, ST_MakeEnvelope({bbox}, ST_SRID(geom)))")
    if where:
        parts.append(f"({where})")
    return f" WHERE {' AND '.join(parts)}" if parts else ""


def _materialise_steps(source: Source) -> list[Step]:
    ingest_id = _ingest_id(source.uri)
    name = Path(source.uri.split("?")[0]).name
    return [
        Step("stage", [source.uri, "--ingest-id", ingest_id],
             "copy the source into the workspace and hash it"),
        Step("ingest-vector",
             [f"/data/work/staging/{ingest_id}/{name}", "--table", ingest_id,
              "--ingest-id", ingest_id],
             "load it into PostGIS, where later steps can reach it"),
    ]


def steps(
    operation: str,
    source: Source,
    decided: Route,
    *,
    bbox: str | None = None,
    where: str | None = None,
    output: str | None = None,
    output_format: str = "gpkg",
    sql_path: str | None = None,
) -> list[Step]:
    """The serial bin/* list that carries out this route, arguments carried through."""
    if decided.strategy is None:
        return []

    if decided.strategy == DUCKDB:
        if operation == EXPORT:
            return [Step("duck-query", [source.uri, *_flags(output=output)],
                         "read the source and write the output file")]
        return [Step("duck-query",
                     [source.uri, *_flags(bbox=bbox, where=where, output=output)],
                     "filter the source in place")]

    if source.format == POSTGIS_TABLE:
        sql = f"SELECT * FROM {source.uri}{_postgis_predicate(bbox, where)}"
        return [Step("export",
                     [output or "/data/outgoing/result.gpkg", "--format", output_format,
                      "--sql", sql],
                     "write the filtered table out")]

    ingest_id = _ingest_id(source.uri)
    plan = _materialise_steps(source)
    if operation == ANALYSE:
        plan.append(
            Step("run-sql", [sql_path or "/data/work/sql/analysis.sql", "--ingest-id", ingest_id],
                 "run the analysis SQL against the ingested tables")
        )
        sql = f"SELECT * FROM analysis_{ingest_id}.result"
    else:
        sql = f"SELECT * FROM raw_{ingest_id}.{ingest_id}{_postgis_predicate(bbox, where)}"
    plan.append(
        Step("export",
             [output or "/data/outgoing/result.gpkg", "--format", output_format, "--sql", sql],
             "write the result out and QC it")
    )
    return plan


def plan(
    operation: str,
    uri: str,
    *,
    materialise: bool = False,
    engine: str | None = None,
    bbox: str | None = None,
    where: str | None = None,
    output: str | None = None,
    output_format: str = "gpkg",
    sql_path: str | None = None,
    asset: dict | None = None,
) -> dict:
    """The whole planning answer: the route, the argument for it, and the steps."""
    source = classify(uri)
    decided = route(operation, source, materialise=materialise, engine=engine)
    decided.warnings.extend(_asset_warnings(operation, asset))
    rendered = steps(
        operation, source, decided,
        bbox=bbox, where=where, output=output, output_format=output_format,
        sql_path=sql_path,
    )
    return {
        "operation": operation,
        "source": {
            "uri": source.uri,
            "format": source.format,
            "locality": source.locality,
            "readers": source.readers,
        },
        "strategy": decided.strategy,
        "reason": decided.reason,
        "fallback": decided.fallback,
        "overridden": decided.overridden,
        "warnings": decided.warnings,
        "blocked_by": decided.blocked_by,
        "steps": [{"command": s.command, "argv": s.argv, "why": s.why} for s in rendered],
    }


def _asset_warnings(operation: str, asset: dict | None) -> list[dict]:
    """Warnings a measured Asset supports and a URI cannot. Never a route change.

    Only measured top-level fields are read. A publisher's `advertised` claims are
    not measurements and Phase 4 quarantined them for that reason.
    """
    if not asset:
        return []
    warnings = []
    if operation == ANALYSE and asset.get("crs_status") == "suspicious":
        warnings.append(
            {
                "code": "CRS_SUSPICIOUS",
                "message": f"The described source reports a suspicious CRS: {asset.get('crs')}",
                "severity": "warning",
            }
        )
    if asset.get("record_count") == 0:
        warnings.append(
            {
                "code": "EMPTY_SOURCE",
                "message": "The described source measured zero records",
                "severity": "warning",
            }
        )
    return warnings
