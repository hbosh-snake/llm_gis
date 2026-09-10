"""The planner's rule table, asserted directly. Nothing here opens a file."""

from __future__ import annotations

import pytest

from llm_gis.errors import UNSUPPORTED_FORMAT, GisError
from llm_gis.planner import DUCKDB, POSTGIS, classify


def test_a_local_geoparquet_is_parquet_and_duckdb_only():
    source = classify("/data/incoming/buildings.parquet")
    assert source.format == "parquet"
    assert source.locality == "local"
    assert source.readers == [DUCKDB]


def test_a_remote_href_is_remote():
    assert classify("https://example.com/a/b.parquet").locality == "remote"
    assert classify("s3://bucket/b.parquet").locality == "remote"


def test_a_query_string_does_not_hide_the_suffix():
    """A signed URL carries its token after the path; duck.reader_sql splits the same way."""
    assert classify("https://example.com/b.parquet?token=abc").format == "parquet"


def test_a_geopackage_is_readable_by_both_engines():
    """DuckDB reads it with ST_Read; ingest-vector loads it. Both routes are real."""
    source = classify("/data/incoming/aoi.gpkg")
    assert source.format == "vector_file"
    assert source.readers == [DUCKDB, POSTGIS]


def test_a_schema_qualified_name_is_a_postgis_table():
    source = classify("analysis_aoi.result")
    assert source.format == "postgis_table"
    assert source.readers == [POSTGIS]


def test_a_raster_has_no_reader_yet():
    """Phase 7 owns cloud raster. Saying so beats guessing a route."""
    source = classify("/data/incoming/dem.tif")
    assert source.format == "raster"
    assert source.readers == []


def test_an_unrecognised_suffix_is_an_error_not_a_guess():
    with pytest.raises(GisError) as caught:
        classify("/data/incoming/notes.docx")
    assert caught.value.code == UNSUPPORTED_FORMAT
