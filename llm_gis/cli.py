from __future__ import annotations

import functools
import json
import sys
from pathlib import Path
from typing import Callable, TypeVar

import typer

from llm_gis.describe import describe_table
from llm_gis.doctor import doctor_report
from llm_gis.errors import GisError
from llm_gis.exporter import export_result
from llm_gis.ingest_raster import ingest_raster
from llm_gis.ingest_vector import ingest_vector
from llm_gis.inspect import inspect_dataset
from llm_gis.list_ingestions import list_ingestions
from llm_gis.run_sql import run_sql_file
from llm_gis.stage import stage_input

app = typer.Typer(help="Headless LLM GIS command entrypoints")

F = TypeVar("F", bound=Callable[..., None])


def handle_errors(func: F) -> F:
    """Render a GisError as JSON on stderr and exit 1, leaving usage errors to typer."""

    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> None:
        try:
            func(*args, **kwargs)
        except GisError as error:
            print(json.dumps(error.to_dict(), indent=2, sort_keys=True), file=sys.stderr)
            raise typer.Exit(code=1)

    return wrapper  # type: ignore[return-value]


@app.command("stage")
@handle_errors
def stage_cmd(
    input_path: Path = typer.Argument(..., help="Path under /data/incoming"),
    ingest_id: str | None = typer.Option(None, help="Optional ingest id"),
) -> None:
    typer.echo(json.dumps(stage_input(input_path, ingest_id=ingest_id), indent=2, sort_keys=True))


@app.command("inspect")
@handle_errors
def inspect_cmd(
    input_path: Path = typer.Argument(..., help="Path to vector/raster input"),
    ingest_id: str | None = typer.Option(None, help="Optional report id"),
) -> None:
    typer.echo(json.dumps(inspect_dataset(input_path, ingest_id=ingest_id), indent=2, sort_keys=True))


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
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


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
    typer.echo(json.dumps(result, indent=2, sort_keys=True))


@app.command("run-sql")
@handle_errors
def run_sql_cmd(
    sql_path: Path = typer.Argument(..., help="SQL file path"),
    ingest_id: str = typer.Option(..., "--ingest-id", help="Target ingest id for search_path"),
    statement_timeout: str = typer.Option("5min", help="Postgres statement timeout"),
) -> None:
    typer.echo(json.dumps(run_sql_file(sql_path, ingest_id=ingest_id, statement_timeout=statement_timeout), indent=2, sort_keys=True))


@app.command("export")
@handle_errors
def export_cmd(
    output_path: Path = typer.Argument(..., help="Output path under /data/outgoing"),
    output_format: str = typer.Option(..., "--format", help="gpkg or geojson"),
    table: str | None = typer.Option(None, help="Table name like analysis_...result"),
    sql_query: str | None = typer.Option(None, "--sql", help="Custom SQL query"),
) -> None:
    typer.echo(
        json.dumps(
            export_result(output_path, output_format, table=table, sql_query=sql_query),
            indent=2,
            sort_keys=True,
        )
    )


@app.command("doctor")
@handle_errors
def doctor_cmd() -> None:
    typer.echo(json.dumps(doctor_report(), indent=2, sort_keys=True))


@app.command("list-ingestions")
@handle_errors
def list_ingestions_cmd(
    limit: int = typer.Option(50, help="Maximum rows to return"),
) -> None:
    typer.echo(json.dumps(list_ingestions(limit=limit), indent=2, sort_keys=True))


@app.command("describe-table")
@handle_errors
def describe_table_cmd(
    table_ref: str = typer.Argument(..., help="Fully qualified table: schema.table"),
) -> None:
    """Show columns and row count for a PostGIS table."""
    if "." not in table_ref:
        raise typer.BadParameter("table_ref must be schema.table, e.g. raw_<ingest_id>.roads")
    schema, table = table_ref.split(".", 1)
    typer.echo(json.dumps(describe_table(schema, table), indent=2, sort_keys=True))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
