from __future__ import annotations

import csv
import json
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest

from llm_gis.common import db_connect
from llm_gis.errors import GisError
from llm_gis.query_sql import (
    _encoded_row_size,
    _json_safe,
    _validate_request,
    query_sql,
)


def test_requires_exactly_one_sql_source(tmp_path: Path) -> None:
    sql_file = tmp_path / "query.sql"
    sql_file.write_text("SELECT 1", encoding="utf-8")

    for kwargs in ({}, {"statement": "SELECT 1", "sql_file": sql_file}):
        with pytest.raises(GisError) as caught:
            query_sql(**kwargs)
        assert caught.value.code == "QUERY_INVALID"


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"max_rows": 0}, "max_rows"),
        ({"max_rows": 10_001}, "max_rows"),
        ({"max_bytes": 0}, "max_bytes"),
        ({"max_bytes": 4_194_305}, "max_bytes"),
        ({"output_format": "geojson"}, "output_format"),
    ],
)
def test_validates_limits_and_format(kwargs: dict, detail: str) -> None:
    with pytest.raises(GisError) as caught:
        _validate_request(statement="SELECT 1", sql_file=None, **kwargs)
    assert caught.value.code == "QUERY_INVALID"
    assert detail in caught.value.message


def test_json_safe_encodes_exact_and_temporal_values() -> None:
    identifier = UUID("fe66f93a-6540-472c-a8a7-a3631dcb0f86")
    value = {
        "decimal": Decimal("1234567890.12345678901234567890"),
        "date": date(2026, 9, 15),
        "time": time(12, 34, 56, 789),
        "datetime": datetime(2026, 9, 15, 12, 34, tzinfo=timezone.utc),
        "uuid": identifier,
        "null": None,
    }

    encoded, warning_codes = _json_safe(value)

    assert encoded == {
        "decimal": "1234567890.12345678901234567890",
        "date": "2026-09-15",
        "time": "12:34:56.000789",
        "datetime": "2026-09-15T12:34:00+00:00",
        "uuid": str(identifier),
        "null": None,
    }
    assert warning_codes == set()


def test_json_safe_recursively_replaces_nonfinite_values() -> None:
    encoded, warning_codes = _json_safe(
        {"values": [float("nan"), {"nested": float("inf")}, Decimal("-Infinity"), 4.0]}
    )

    assert encoded == {"values": [None, {"nested": None}, None, 4.0]}
    assert warning_codes == {"NONFINITE_VALUE_REPLACED"}
    json.dumps(encoded, allow_nan=False)


def test_json_safe_does_not_emit_repr_for_unsupported_values() -> None:
    encoded, warning_codes = _json_safe(object())

    assert encoded is None
    assert warning_codes == {"UNSUPPORTED_VALUE_OMITTED"}


def test_encoded_row_size_uses_compact_utf8_and_exact_boundaries() -> None:
    row = ["é"]
    exact = len(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    assert _encoded_row_size(row) == exact
    assert exact == 6


@pytest.fixture(scope="module")
def query_fixture() -> dict[str, str]:
    ingest_id = f"q{uuid4().hex[:16]}"
    raw_schema = f"raw_{ingest_id}"
    analysis_schema = f"analysis_{ingest_id}"
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                psycopg.sql.SQL("CREATE SCHEMA {};").format(
                    psycopg.sql.Identifier(raw_schema)
                )
            )
            cur.execute(
                psycopg.sql.SQL(
                    "CREATE TABLE {}.items (id integer PRIMARY KEY, label text, geom geometry(Point, 4326), payload bytea);"
                ).format(psycopg.sql.Identifier(raw_schema))
            )
            cur.execute(
                psycopg.sql.SQL(
                    "INSERT INTO {}.items (id, label, geom, payload) VALUES "
                    "(2, 'beta', ST_SetSRID(ST_Point(12, 42), 4326), decode('beef', 'hex')), "
                    "(1, 'alpha', ST_SetSRID(ST_Point(11, 41), 4326), decode('cafe', 'hex')), "
                    "(3, 'gamma', ST_SetSRID(ST_Point(13, 43), 4326), decode('fade', 'hex'));"
                ).format(psycopg.sql.Identifier(raw_schema))
            )
    yield {
        "ingest_id": ingest_id,
        "raw_schema": raw_schema,
        "analysis_schema": analysis_schema,
    }
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE;").format(
                    psycopg.sql.Identifier(raw_schema)
                )
            )
            cur.execute(
                psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE;").format(
                    psycopg.sql.Identifier(analysis_schema)
                )
            )


@pytest.mark.live
def test_duplicate_columns_are_positional_and_empty_results_are_typed() -> None:
    duplicate = query_sql(statement="SELECT 1 AS value, 2 AS value")
    empty = query_sql(statement="SELECT 1::integer AS n, 'x'::text AS label WHERE false")

    assert [column["name"] for column in duplicate["columns"]] == ["value", "value"]
    assert duplicate["rows"] == [[1, 2]]
    assert empty["rows"] == []
    assert empty["returned_row_count"] == 0
    assert [column["type"] for column in empty["columns"]] == ["int4", "text"]


@pytest.mark.live
def test_named_cursor_rejects_batch_but_accepts_literal_semicolon() -> None:
    assert query_sql(statement="SELECT ';' AS value")["rows"] == [[";"]]
    with pytest.raises(GisError) as caught:
        query_sql(statement="SELECT 1; SELECT 2")
    assert caught.value.code == "QUERY_FAILED"


@pytest.mark.live
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO items (id, label) VALUES (99, 'write')",
        "CREATE TABLE forbidden (id integer)",
        "WITH changed AS (DELETE FROM items WHERE id = 1 RETURNING id) SELECT * FROM changed",
    ],
)
def test_read_only_rejects_writes_without_changing_fixture(
    query_fixture: dict[str, str], statement: str
) -> None:
    before = query_sql(
        statement="SELECT count(*) FROM items", ingest_id=query_fixture["ingest_id"]
    )["rows"]

    with pytest.raises(GisError) as caught:
        query_sql(statement=statement, ingest_id=query_fixture["ingest_id"])

    assert caught.value.code == "QUERY_FAILED"
    assert query_sql(
        statement="SELECT count(*) FROM items", ingest_id=query_fixture["ingest_id"]
    )["rows"] == before


@pytest.mark.live
def test_statement_timeout_is_bound_and_enforced() -> None:
    with pytest.raises(GisError) as caught:
        query_sql(statement="SELECT pg_sleep(0.1)", statement_timeout="10ms")
    assert caught.value.code == "QUERY_FAILED"


@pytest.mark.live
def test_unicode_byte_limit_has_exact_boundary() -> None:
    exact = query_sql(statement="SELECT 'é' AS value", max_bytes=6)
    too_small = query_sql(statement="SELECT 'é' AS value", max_bytes=5)

    assert exact["rows"] == [["é"]]
    assert exact["truncated"] is False
    assert too_small["rows"] == []
    assert too_small["returned_row_count"] == 0
    assert too_small["truncated"] is True
    assert too_small["truncation_reason"] == "max_bytes"


@pytest.mark.live
def test_huge_first_row_is_not_sliced() -> None:
    result = query_sql(statement="SELECT repeat('é', 100) AS value", max_bytes=20)

    assert result["rows"] == []
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_bytes"


@pytest.mark.live
def test_recursive_nonfinite_database_values_warn() -> None:
    result = query_sql(
        statement="SELECT ARRAY['NaN'::float8, 'Infinity'::float8, 1.5] AS values"
    )

    assert result["rows"] == [[[None, None, 1.5]]]
    assert [warning["code"] for warning in result["warnings"]] == [
        "NONFINITE_VALUE_REPLACED"
    ]


@pytest.mark.live
def test_geometry_geography_and_binary_are_omitted_by_oid(
    query_fixture: dict[str, str]
) -> None:
    result = query_sql(
        statement=(
            "SELECT id, geom, geom::geography AS geog, payload, ST_AsText(geom) AS geom_text "
            "FROM items ORDER BY id"
        ),
        ingest_id=query_fixture["ingest_id"],
    )

    assert [column["name"] for column in result["columns"]] == ["id", "geom_text"]
    assert result["rows"][0] == [1, "POINT(11 41)"]
    assert [(column["name"], column["type"]) for column in result["omitted_columns"]] == [
        ("geom", "geometry"),
        ("geog", "geography"),
        ("payload", "bytea"),
    ]


@pytest.mark.live
def test_deterministic_order_and_ingest_search_path(query_fixture: dict[str, str]) -> None:
    result = query_sql(
        statement="SELECT id, label FROM items ORDER BY id",
        ingest_id=query_fixture["ingest_id"],
    )

    assert result["rows"] == [[1, "alpha"], [2, "beta"], [3, "gamma"]]


@pytest.mark.live
def test_full_json_export_outlives_preview_limit(tmp_path: Path) -> None:
    out = tmp_path / "all.json"
    result = query_sql(
        statement="SELECT generate_series(1,3) AS n", max_rows=1, output=out
    )

    assert result["rows"] == [[1]]
    assert result["truncated"] is True
    assert result["truncation_reason"] == "max_rows"
    assert result["exported_row_count"] == 3
    assert len(json.loads(out.read_text(encoding="utf-8"))["rows"]) == 3


@pytest.mark.live
def test_full_csv_export_outlives_preview_and_preserves_duplicate_headers(
    tmp_path: Path,
) -> None:
    out = tmp_path / "all.csv"
    result = query_sql(
        statement="SELECT n, NULL::text AS value, n + 10 AS value FROM generate_series(1,3) AS n ORDER BY n",
        max_rows=1,
        output=out,
        output_format="csv",
    )

    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows == [
        ["n", "value", "value"],
        ["1", "", "11"],
        ["2", "", "12"],
        ["3", "", "13"],
    ]
    assert result["exported_row_count"] == 3


@pytest.mark.live
def test_existing_output_is_refused_and_partial_created_output_is_removed(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(GisError) as caught:
        query_sql(statement="SELECT 1", output=existing)
    assert caught.value.code == "OUTPUT_EXISTS"
    assert existing.read_text(encoding="utf-8") == "keep"

    partial = tmp_path / "partial.json"
    with pytest.raises(GisError):
        query_sql(statement="SELECT 1 / 0", output=partial)
    assert not partial.exists()
