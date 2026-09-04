from __future__ import annotations

import functools
import json
import sys
from pathlib import Path
from typing import Callable, TypeVar

import typer

from llm_gis.describe import describe_table
from llm_gis.doctor import doctor_report
from llm_gis.errors import UNEXPECTED, GisError
from llm_gis.exporter import export_result
from llm_gis.ingest_raster import ingest_raster
from llm_gis.ingest_vector import ingest_vector
from llm_gis.inspect import inspect_dataset
from llm_gis.list_ingestions import list_ingestions
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
        except typer.Exit:
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
    input_path: Path = typer.Argument(..., help="Path to vector/raster input"),
    ingest_id: str | None = typer.Option(None, help="Optional report id"),
) -> None:
    _emit("inspect", inspect_dataset(input_path, ingest_id=ingest_id))


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
    output_format: str = typer.Option(..., "--format", help="gpkg or geojson"),
    table: str | None = typer.Option(None, help="Table name like analysis_...result"),
    sql_query: str | None = typer.Option(None, "--sql", help="Custom SQL query"),
) -> None:
    _emit("export", export_result(output_path, output_format, table=table, sql_query=sql_query))


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
