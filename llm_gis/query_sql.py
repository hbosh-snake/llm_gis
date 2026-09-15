from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO
from uuid import UUID

import psycopg
from psycopg import sql

from llm_gis.common import db_connect, sanitize_identifier
from llm_gis.errors import GisError

MAX_ROWS = 10_000
MAX_BYTES = 4_194_304
FETCH_BATCH_SIZE = 1_000

QUERY_INVALID = "QUERY_INVALID"
QUERY_FAILED = "QUERY_FAILED"
OUTPUT_EXISTS = "OUTPUT_EXISTS"

_BINARY_TYPE_NAMES = {"bytea", "geometry", "geography"}
_DECIMAL_TYPE_NAMES = {"numeric", "decimal"}
_TEMPORAL_TYPE_NAMES = {
    "date",
    "time",
    "timetz",
    "timestamp",
    "timestamptz",
}


def _query_error(message: str, *, details: dict[str, object] | None = None) -> GisError:
    return GisError(
        QUERY_INVALID,
        message,
        "Provide one read-only SELECT, VALUES, or WITH ... SELECT query and valid preview limits",
        details,
    )


def _validate_request(
    *,
    statement: str | None,
    sql_file: Path | None,
    max_rows: int = 100,
    max_bytes: int = 262_144,
    output_format: str = "json",
) -> None:
    if (statement is None) == (sql_file is None):
        raise _query_error("Exactly one of statement and sql_file is required")
    if statement is not None and not statement.strip():
        raise _query_error("statement must not be empty")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= MAX_ROWS:
        raise _query_error(f"max_rows must be between 1 and {MAX_ROWS}")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1 <= max_bytes <= MAX_BYTES:
        raise _query_error(f"max_bytes must be between 1 and {MAX_BYTES}")
    if output_format not in {"json", "csv"}:
        raise _query_error("output_format must be json or csv")


def _json_safe(value: Any) -> tuple[Any, set[str]]:
    """Return a JSON-safe value and warning codes produced while encoding it."""
    if value is None or isinstance(value, (str, bool, int)):
        return value, set()
    if isinstance(value, float):
        if math.isfinite(value):
            return value, set()
        return None, {"NONFINITE_VALUE_REPLACED"}
    if isinstance(value, Decimal):
        if value.is_finite():
            return str(value), set()
        return None, {"NONFINITE_VALUE_REPLACED"}
    if isinstance(value, (datetime, date, time)):
        return value.isoformat(), set()
    if isinstance(value, UUID):
        return str(value), set()
    if isinstance(value, (list, tuple)):
        encoded: list[Any] = []
        warnings: set[str] = set()
        for item in value:
            safe_item, item_warnings = _json_safe(item)
            encoded.append(safe_item)
            warnings.update(item_warnings)
        return encoded, warnings
    if isinstance(value, dict):
        encoded_dict: dict[str, Any] = {}
        warnings: set[str] = set()
        for key, item in value.items():
            if not isinstance(key, str):
                warnings.add("UNSUPPORTED_VALUE_OMITTED")
                continue
            safe_item, item_warnings = _json_safe(item)
            encoded_dict[key] = safe_item
            warnings.update(item_warnings)
        return encoded_dict, warnings
    return None, {"UNSUPPORTED_VALUE_OMITTED"}


def _encoded_row_size(row: list[Any]) -> int:
    return len(
        json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _encoding_for_type(type_name: str) -> str:
    if type_name in _DECIMAL_TYPE_NAMES:
        return "decimal-string"
    if type_name in _TEMPORAL_TYPE_NAMES:
        return "iso8601"
    if type_name == "uuid":
        return "uuid-string"
    return "json"


def _warning(code: str) -> dict[str, str]:
    if code == "NONFINITE_VALUE_REPLACED":
        return {
            "code": code,
            "message": "One or more NaN or infinity values were returned as null",
        }
    return {
        "code": code,
        "message": "One or more unsupported values were returned as null or omitted from an object",
    }


def _read_statement(statement: str | None, sql_file: Path | None) -> str:
    if statement is not None:
        return statement
    assert sql_file is not None
    try:
        text = sql_file.read_text(encoding="utf-8")
    except OSError as error:
        raise _query_error(
            f"Could not read sql_file: {sql_file}", details={"reason": str(error)}
        ) from error
    if not text.strip():
        raise _query_error("sql_file must not be empty")
    return text


def _open_output(path: Path) -> TextIO:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("x", encoding="utf-8", newline="")
    except FileExistsError as error:
        raise GisError(
            OUTPUT_EXISTS,
            f"Output already exists: {path}",
            "Choose a new output path",
        ) from error
    except OSError as error:
        raise GisError(
            QUERY_FAILED,
            f"Could not create output: {path}",
            "Check that the parent directory is writable and choose a new path",
            {"reason": str(error)},
        ) from error


def _type_names(control: psycopg.Cursor[Any], type_oids: set[int]) -> dict[int, str]:
    if not type_oids:
        return {}
    control.execute(
        "SELECT oid, typname FROM pg_type WHERE oid = ANY(%s::oid[])",
        (sorted(type_oids),),
    )
    return {int(oid): str(name) for oid, name in control.fetchall()}


def _configure_transaction(
    control: psycopg.Cursor[Any], statement_timeout: str, ingest_id: str | None
) -> set[int]:
    control.execute(
        "SELECT set_config('statement_timeout', %s, true)",
        (statement_timeout,),
    )
    if ingest_id is not None:
        try:
            sid = sanitize_identifier(ingest_id)
        except ValueError as error:
            raise _query_error(f"Invalid ingest_id: {ingest_id}") from error
        control.execute(
            sql.SQL("SET LOCAL search_path TO {}, {}, public").format(
                sql.Identifier(f"analysis_{sid}"),
                sql.Identifier(f"raw_{sid}"),
            )
        )
    control.execute(
        "SELECT oid FROM pg_type WHERE typname IN ('geometry', 'geography')"
    )
    return {int(row[0]) for row in control.fetchall()}


def _column_projection(
    description: list[Any] | tuple[Any, ...],
    type_names: dict[int, str],
    spatial_oids: set[int],
) -> tuple[list[int], list[dict[str, str]], list[dict[str, str]]]:
    included_indexes: list[int] = []
    columns: list[dict[str, str]] = []
    omitted_columns: list[dict[str, str]] = []
    for index, item in enumerate(description):
        oid = int(item.type_code)
        type_name = type_names.get(oid, f"oid_{oid}")
        metadata = {
            "name": str(item.name),
            "type": type_name,
            "encoding": _encoding_for_type(type_name),
        }
        if oid in spatial_oids or type_name in _BINARY_TYPE_NAMES:
            omitted_columns.append(metadata)
        else:
            included_indexes.append(index)
            columns.append(metadata)
    return included_indexes, columns, omitted_columns


def _write_json_prefix(output_handle: TextIO, columns: list[dict[str, str]]) -> None:
    output_handle.write('{"columns":')
    json.dump(columns, output_handle, ensure_ascii=False, separators=(",", ":"))
    output_handle.write(',"rows":[')


def query_sql(
    *,
    statement: str | None = None,
    sql_file: Path | None = None,
    ingest_id: str | None = None,
    statement_timeout: str = "5min",
    max_rows: int = 100,
    max_bytes: int = 262_144,
    output: Path | None = None,
    output_format: str = "json",
) -> dict:
    """Run one read-only PostgreSQL row query with a bounded inline preview."""
    _validate_request(
        statement=statement,
        sql_file=sql_file,
        max_rows=max_rows,
        max_bytes=max_bytes,
        output_format=output_format,
    )
    query_text = _read_statement(statement, sql_file)

    output_handle: TextIO | None = None
    output_created = False
    completed = False
    if output is not None:
        output_handle = _open_output(output)
        output_created = True

    connection: psycopg.Connection[Any] | None = None
    try:
        connection = db_connect()
        connection.read_only = True
        with connection.transaction():
            with connection.cursor() as control:
                spatial_oids = _configure_transaction(
                    control, statement_timeout, ingest_id
                )
                with connection.cursor(name="llm_gis_query_sql") as cursor:
                    cursor.execute(query_text)
                    description = list(cursor.description or [])
                    if not description:
                        raise _query_error(
                            "The statement does not return rows; use SELECT, VALUES, or WITH ... SELECT"
                        )
                    type_oids = {int(item.type_code) for item in description}
                    type_names = _type_names(control, type_oids)
                    included, columns, omitted_columns = _column_projection(
                        description, type_names, spatial_oids
                    )

                    csv_writer: Any = None
                    first_json_row = True
                    if output_handle is not None:
                        if output_format == "json":
                            _write_json_prefix(output_handle, columns)
                        else:
                            csv_writer = csv.writer(output_handle)
                            csv_writer.writerow([column["name"] for column in columns])

                    preview_rows: list[list[Any]] = []
                    preview_bytes = 0
                    truncated = False
                    truncation_reason: str | None = None
                    warning_codes: set[str] = set()
                    exported_row_count = 0
                    preview_closed = False
                    source_rows_seen = 0

                    while True:
                        if output_handle is None:
                            remaining = max_rows + 1 - source_rows_seen
                            if remaining <= 0 or preview_closed:
                                break
                            fetch_size = min(FETCH_BATCH_SIZE, remaining)
                        else:
                            fetch_size = FETCH_BATCH_SIZE
                        batch = cursor.fetchmany(fetch_size)
                        if not batch:
                            break
                        for source_row in batch:
                            source_rows_seen += 1
                            encoded_row: list[Any] = []
                            for index in included:
                                safe_value, value_warnings = _json_safe(source_row[index])
                                encoded_row.append(safe_value)
                                warning_codes.update(value_warnings)

                            if output_handle is not None:
                                if output_format == "json":
                                    if not first_json_row:
                                        output_handle.write(",")
                                    json.dump(
                                        encoded_row,
                                        output_handle,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                        allow_nan=False,
                                    )
                                    first_json_row = False
                                else:
                                    csv_writer.writerow(encoded_row)
                                exported_row_count += 1

                            if not preview_closed:
                                if len(preview_rows) >= max_rows:
                                    truncated = True
                                    truncation_reason = "max_rows"
                                    preview_closed = True
                                else:
                                    row_size = _encoded_row_size(encoded_row)
                                    if preview_bytes + row_size > max_bytes:
                                        truncated = True
                                        truncation_reason = "max_bytes"
                                        preview_closed = True
                                    else:
                                        preview_rows.append(encoded_row)
                                        preview_bytes += row_size
                        if output_handle is None and preview_closed:
                            break

                    if output_handle is not None and output_format == "json":
                        output_handle.write("]}")

        result: dict[str, Any] = {
            "engine": "postgis",
            "columns": columns,
            "rows": preview_rows,
            "returned_row_count": len(preview_rows),
            "truncated": truncated,
            "truncation_reason": truncation_reason,
            "omitted_columns": omitted_columns,
            "warnings": [_warning(code) for code in sorted(warning_codes)],
        }
        if output is not None:
            result.update(
                {
                    "output_path": str(output),
                    "output_format": output_format,
                    "exported_row_count": exported_row_count,
                }
            )
        completed = True
        return result
    except GisError:
        raise
    except psycopg.Error as error:
        raise GisError(
            QUERY_FAILED,
            "PostgreSQL could not run the read-only query",
            "Check that the SQL is one SELECT, VALUES, or WITH ... SELECT statement and that its tables and columns exist",
            {"database_error": str(error)},
        ) from error
    except OSError as error:
        raise GisError(
            QUERY_FAILED,
            "Could not write the complete query export",
            "Check the output path and available disk space, then choose a new output path",
            {"reason": str(error)},
        ) from error
    finally:
        if connection is not None:
            connection.close()
        if output_handle is not None:
            output_handle.close()
        if output_created and not completed and output is not None:
            try:
                output.unlink()
            except FileNotFoundError:
                pass
