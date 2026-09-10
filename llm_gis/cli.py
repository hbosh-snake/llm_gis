from __future__ import annotations

import functools
import json
import sys
from pathlib import Path
from typing import Callable, TypeVar

import typer
from typer._click.exceptions import UsageError

from llm_gis import catalog as catalog_ops
from llm_gis.describe import describe_table
from llm_gis.duck import describe as duck_describe
from llm_gis.doctor import doctor_report
from llm_gis.errors import INPUT_NOT_FOUND, UNEXPECTED, GisError
from llm_gis.exporter import export_result
from llm_gis.ingest_raster import ingest_raster
from llm_gis.ingest_vector import ingest_vector
from llm_gis.inspect import inspect_dataset
from llm_gis.list_ingestions import list_ingestions
from llm_gis.planner import plan as plan_operation
from llm_gis.qc import QcContext, qc_report, reference_for
from llm_gis.query import query as duck_query
from llm_gis.run_sql import run_sql_file
from llm_gis.stage import stage_input

app = typer.Typer(help="Headless LLM GIS command entrypoints")

F = TypeVar("F", bound=Callable[..., None])


def _fail(error: GisError) -> None:
    print(json.dumps(error.to_dict(), indent=2, sort_keys=True), file=sys.stderr)
    raise typer.Exit(code=1)


def _emit(command: str, result: dict) -> None:
    """Print a success result with the stable status/command envelope."""
    envelope = {**result, "status": "ok", "command": command}
    typer.echo(json.dumps(envelope, indent=2, sort_keys=True))


def handle_errors(func: F) -> F:
    """Render a GisError as JSON on stderr and exit 1, leaving usage errors to typer."""

    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> None:
        try:
            func(*args, **kwargs)
        except GisError as error:
            _fail(error)
        except (typer.Exit, typer.Abort, UsageError):
            raise
        except Exception as error:
            _fail(
                GisError(
                    UNEXPECTED,
                    f"{type(error).__name__}: {error}",
                    "This is an unhandled failure; report it with the command that produced it",
                )
            )

    return wrapper  # type: ignore[return-value]


@app.command("stage")
@handle_errors
def stage_cmd(
    input_path: Path = typer.Argument(..., help="Path under /data/incoming"),
    ingest_id: str | None = typer.Option(None, help="Optional ingest id"),
) -> None:
    _emit("stage", stage_input(input_path, ingest_id=ingest_id))


@app.command("inspect")
@handle_errors
def inspect_cmd(
    source: str = typer.Argument(..., help="Path or http/https/s3 URI to a vector or raster"),
    ingest_id: str | None = typer.Option(None, help="Optional report id"),
) -> None:
    _emit("inspect", inspect_dataset(source, ingest_id=ingest_id))


@app.command("ingest-vector")
@handle_errors
def ingest_vector_cmd(
    input_path: Path = typer.Argument(..., help="Path to vector dataset"),
    table: str = typer.Option(..., "--table", help="Destination table name"),
    ingest_id: str | None = typer.Option(None, help="Optional ingest id"),
    schema: str | None = typer.Option(None, help="Destination schema, default raw_<ingest_id>"),
    src_crs: str | None = typer.Option(None, "--src-crs", help="Source CRS override (for missing/suspicious CRS)"),
    dst_crs: str | None = typer.Option(None, "--dst-crs", help="Destination CRS (reproject on load)"),
) -> None:
    result = ingest_vector(input_path, table=table, ingest_id=ingest_id, src_crs=src_crs, dst_crs=dst_crs, schema=schema)
    _emit("ingest-vector", result)


@app.command("ingest-raster")
@handle_errors
def ingest_raster_cmd(
    input_path: Path = typer.Argument(..., help="Path to raster dataset"),
    table: str = typer.Option(..., "--table", help="Destination table name"),
    ingest_id: str | None = typer.Option(None, help="Optional ingest id"),
    schema: str | None = typer.Option(None, help="Destination schema, default raw_<ingest_id>"),
    src_crs: str | None = typer.Option(None, "--src-crs", help="Source CRS override (for missing/suspicious CRS)"),
    dst_crs: str | None = typer.Option(None, "--dst-crs", help="Destination CRS (reproject before load)"),
) -> None:
    result = ingest_raster(input_path, table=table, ingest_id=ingest_id, src_crs=src_crs, dst_crs=dst_crs, schema=schema)
    _emit("ingest-raster", result)


@app.command("run-sql")
@handle_errors
def run_sql_cmd(
    sql_path: Path = typer.Argument(..., help="SQL file path"),
    ingest_id: str = typer.Option(..., "--ingest-id", help="Target ingest id for search_path"),
    statement_timeout: str = typer.Option("5min", help="Postgres statement timeout"),
) -> None:
    _emit("run-sql", run_sql_file(sql_path, ingest_id=ingest_id, statement_timeout=statement_timeout))


@app.command("export")
@handle_errors
def export_cmd(
    output_path: Path = typer.Argument(..., help="Output path under /data/outgoing"),
    output_format: str = typer.Option(..., "--format", help="gpkg, geojson or parquet"),
    table: str | None = typer.Option(None, help="Table name like analysis_...result"),
    sql_query: str | None = typer.Option(None, "--sql", help="Custom SQL query"),
    qc: bool = typer.Option(True, "--qc/--no-qc", help="Attach a QC block to the result"),
    compare_to: str | None = typer.Option(None, "--compare-to", help="Table or file whose extent the result should overlap"),
) -> None:
    _emit(
        "export",
        export_result(
            output_path, output_format, table=table, sql_query=sql_query,
            qc=qc, compare_to=compare_to,
        ),
    )


@app.command("qc")
@handle_errors
def qc_cmd(
    ref: str = typer.Argument(..., help="File path, or schema.table"),
    expect_non_empty: bool = typer.Option(False, "--expect-non-empty", help="Treat an empty result as a problem"),
    metric_op: bool = typer.Option(False, "--metric-op", help="This data feeds areas, lengths or distances"),
    compare_to: str | None = typer.Option(None, "--compare-to", help="File or table whose extent this should overlap"),
    id_column: str | None = typer.Option(None, "--id-column", help="Column to check for duplicate identifiers"),
    exact_stats: bool = typer.Option(False, "--exact-stats", help="Full raster pixel scan instead of an approximation"),
) -> None:
    """Deterministic metrics and warnings for a dataset or a table."""
    context = QcContext(
        expect_non_empty=expect_non_empty,
        metric_op=metric_op,
        id_column=id_column,
        reference=reference_for(compare_to) if compare_to else None,
    )
    _emit("qc", qc_report(ref, context, exact_stats=exact_stats))


@app.command("duck-describe")
@handle_errors
def duck_describe_cmd(
    uri: str = typer.Argument(..., help="Path or URL of a Parquet/GeoParquet source"),
) -> None:
    """Schema, row count, CRS and bbox of a Parquet source, without materialising it."""
    _emit("duck-describe", duck_describe(uri))


@app.command("duck-query")
@handle_errors
def duck_query_cmd(
    uri: str = typer.Argument(..., help="Path or URL of a Parquet/GeoParquet source"),
    bbox: str | None = typer.Option(None, "--bbox", help="minx,miny,maxx,maxy in the source CRS"),
    where: str | None = typer.Option(None, "--where", help="SQL predicate on attributes"),
    columns: str | None = typer.Option(None, "--columns", help="Comma-separated columns to keep"),
    limit: int | None = typer.Option(None, "--limit", help="Maximum rows"),
    output_path: Path | None = typer.Option(None, "--output", help="Write matches to this GeoParquet file"),
) -> None:
    """Filter a Parquet source by bbox and attributes, optionally writing the subset."""
    parsed_bbox = None
    if bbox:
        parts = [p.strip() for p in bbox.split(",")]
        if len(parts) != 4:
            raise typer.BadParameter("--bbox must be minx,miny,maxx,maxy")
        parsed_bbox = tuple(float(p) for p in parts)
    _emit(
        "duck-query",
        duck_query(
            uri,
            bbox=parsed_bbox,
            where=where,
            columns=[c.strip() for c in columns.split(",")] if columns else None,
            limit=limit,
            output_path=output_path,
        ),
    )


@app.command("plan")
@handle_errors
def plan_cmd(
    operation: str = typer.Argument(..., help="query, analyse or export"),
    uri: str = typer.Argument(..., help="Path, URL or schema.table of the source"),
    bbox: str | None = typer.Option(None, "--bbox", help="minx,miny,maxx,maxy in the source CRS"),
    where: str | None = typer.Option(None, "--where", help="SQL predicate on attributes"),
    output: str | None = typer.Option(None, "--output", help="Where the emitted steps should write"),
    output_format: str = typer.Option("gpkg", "--format", help="gpkg, geojson or parquet"),
    sql_path: str | None = typer.Option(None, "--sql-file", help="SQL file for an analyse plan"),
    engine: str | None = typer.Option(None, "--engine", help="Force duckdb or postgis"),
    materialise: bool = typer.Option(False, "--materialise/--no-materialise",
                                     help="The result must survive for later steps"),
    asset: Path | None = typer.Option(None, "--asset", help="An Asset JSON file for extra warnings"),
) -> None:
    """Explain which engine should run an operation, why, and the steps. Runs nothing."""
    asset_json = None
    if asset is not None:
        if not asset.exists():
            raise GisError(
                INPUT_NOT_FOUND,
                f"Asset file does not exist: {asset}",
                "Pass the JSON emitted by duck-describe, inspect or catalog-assets",
            )
        asset_json = json.loads(asset.read_text(encoding="utf-8"))
    _emit(
        "plan",
        plan_operation(
            operation, uri, materialise=materialise, engine=engine, bbox=bbox,
            where=where, output=output, output_format=output_format,
            sql_path=sql_path, asset=asset_json,
        ),
    )


def _parse_bbox(bbox: str | None) -> list[float] | None:
    """Four comma-separated numbers, always lon/lat WGS84 for STAC."""
    if bbox is None:
        return None
    parts = [p.strip() for p in bbox.split(",")]
    if len(parts) != 4:
        raise typer.BadParameter("--bbox must be minx,miny,maxx,maxy in lon/lat")
    return [float(p) for p in parts]


@app.command("catalog-collections")
@handle_errors
def catalog_collections_cmd(
    catalog: str = typer.Argument(..., help="Catalogue alias or URL"),
) -> None:
    """Collections a STAC catalogue offers. Never downloads an asset."""
    _emit("catalog-collections", catalog_ops.list_collections(catalog))


@app.command("catalog-search")
@handle_errors
def catalog_search_cmd(
    catalog: str = typer.Argument(..., help="Catalogue alias or URL"),
    collection: str | None = typer.Option(None, "--collection", help="Restrict to one collection id"),
    bbox: str | None = typer.Option(None, "--bbox", help="minx,miny,maxx,maxy in lon/lat WGS84"),
    datetime_spec: str | None = typer.Option(None, "--datetime", help="RFC 3339 instant or start/end range"),
    limit: int = typer.Option(100, "--limit", help="Maximum items to return"),
) -> None:
    """Find items by area and time. Discovery only: no asset bytes are fetched."""
    _emit(
        "catalog-search",
        catalog_ops.search_items(
            catalog,
            collection=collection,
            bbox=_parse_bbox(bbox),
            datetime_spec=datetime_spec,
            limit=limit,
        ),
    )


@app.command("catalog-item")
@handle_errors
def catalog_item_cmd(
    item_url: str = typer.Argument(..., help="Item URL, the 'self' field from catalog-search"),
) -> None:
    """One STAC item, with its properties passed through verbatim."""
    _emit("catalog-item", catalog_ops.get_item(item_url))


@app.command("catalog-assets")
@handle_errors
def catalog_assets_cmd(
    item_url: str = typer.Argument(..., help="Item URL, the 'self' field from catalog-search"),
    role: str | None = typer.Option(None, "--role", help="Keep only assets carrying this role"),
    media_type: str | None = typer.Option(None, "--media-type", help="Keep only this exact media type"),
) -> None:
    """Asset hrefs and advertised metadata. A duckdb-readable href feeds duck-query."""
    _emit("catalog-assets", catalog_ops.get_assets(item_url, role=role, media_type=media_type))


@app.command("doctor")
@handle_errors
def doctor_cmd() -> None:
    _emit("doctor", doctor_report())


@app.command("list-ingestions")
@handle_errors
def list_ingestions_cmd(
    limit: int = typer.Option(50, help="Maximum rows to return"),
) -> None:
    _emit("list-ingestions", list_ingestions(limit=limit))


@app.command("describe-table")
@handle_errors
def describe_table_cmd(
    table_ref: str = typer.Argument(..., help="Fully qualified table: schema.table"),
) -> None:
    """Show columns and row count for a PostGIS table."""
    if "." not in table_ref:
        raise typer.BadParameter("table_ref must be schema.table, e.g. raw_<ingest_id>.roads")
    schema, table = table_ref.split(".", 1)
    _emit("describe-table", describe_table(schema, table))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
