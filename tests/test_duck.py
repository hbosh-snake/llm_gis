"""DuckDB path: everything here runs offline against the committed fixture."""

import json
from pathlib import Path

import pytest

from llm_gis.duck import describe
from llm_gis.errors import COMMAND_FAILED, MISSING_ARGUMENT, GisError
from llm_gis.query import query

FIXTURE = str(Path(__file__).parent / "fixtures" / "aoi.parquet")


def test_describe_reports_schema_crs_and_bbox():
    report = describe(FIXTURE)
    assert report["row_count"] == 4
    assert report["geometry_column"] == "geom"
    assert report["crs"] == "EPSG:4326"
    assert report["bbox"]["minx"] == pytest.approx(10.0)
    assert {c["name"] for c in report["columns"]} == {"fid", "id", "name", "geom"}


def test_describe_raises_for_an_unreadable_source():
    with pytest.raises(GisError) as caught:
        describe("/nowhere/missing.parquet")
    assert caught.value.code == COMMAND_FAILED


def test_bbox_filter_selects_a_subset():
    assert query(FIXTURE, bbox=(10.0, 45.0, 10.15, 45.15))["matched_row_count"] == 1


def test_bbox_filter_that_matches_nothing_is_not_an_error():
    """An empty result is a real answer, not a failure."""
    result = query(FIXTURE, bbox=(0.0, 0.0, 1.0, 1.0))
    assert result["matched_row_count"] == 0
    assert result["source_row_count"] == 4


def test_attribute_filter():
    assert query(FIXTURE, where="name = 'north'")["matched_row_count"] == 1


def test_writing_a_subset_round_trips(tmp_path):
    out = tmp_path / "subset.parquet"
    result = query(FIXTURE, bbox=(10.0, 45.0, 10.15, 45.15), output_path=out)
    assert result["output_path"] == str(out)
    written = describe(str(out))
    assert written["row_count"] == 1
    assert written["crs"] == "EPSG:4326"


def test_writing_a_subset_as_geopackage_produces_an_ingestible_file(tmp_path):
    """The conversion path bin/plan points to for a materialised Parquet query."""
    import subprocess

    out = tmp_path / "subset.gpkg"
    result = query(FIXTURE, bbox=(10.0, 45.0, 10.15, 45.15), output_path=out, output_format="geopackage")
    assert result["output_format"] == "geopackage"
    assert out.exists()
    info = json.loads(subprocess.run(
        ["ogrinfo", "-json", "-ro", str(out)], capture_output=True, text=True, check=True
    ).stdout)
    assert info["layers"][0]["featureCount"] == 1


def test_an_unsupported_output_format_is_refused():
    with pytest.raises(GisError) as caught:
        query(FIXTURE, output_path=Path("/tmp/x.shp"), output_format="shapefile")
    assert caught.value.code == "UNSUPPORTED_FORMAT"


def test_bbox_without_geometry_is_refused(tmp_path):
    """A bbox on plain Parquet is a mistake worth naming, not a silent empty result."""
    from llm_gis.duck import connect

    plain = tmp_path / "plain.parquet"
    connect().execute(f"COPY (SELECT 1 AS a) TO '{plain}' (FORMAT PARQUET)")
    with pytest.raises(GisError) as caught:
        query(str(plain), bbox=(0, 0, 1, 1))
    assert caught.value.code == MISSING_ARGUMENT


def test_a_bad_where_clause_reports_the_duckdb_error():
    with pytest.raises(GisError) as caught:
        query(FIXTURE, where="no_such_column = 1")
    assert caught.value.code == COMMAND_FAILED
    assert "duckdb_error" in caught.value.details
