"""File collectors against the committed fixtures. Offline, given a warm
DuckDB extension cache -- the same caveat tests/test_duck.py carries."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_gis.errors import INPUT_NOT_FOUND, GisError
from llm_gis.qc import QcContext, qc_report

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_clean_geopackage_reports_its_metrics():
    report = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext())
    metrics = report["metrics"]
    assert report["source"]["kind"] == "file"
    assert report["source"]["dataset_kind"] == "vector"
    assert metrics["crs"] == "EPSG:4326"
    assert metrics["vector"]["feature_count"] == 4
    assert metrics["vector"]["invalid_count"] == 0
    assert metrics["vector"]["empty_count"] == 0
    assert metrics["bbox"]["minx"] == pytest.approx(10.0)
    assert metrics["vector"]["area_stats"]["sum"] > 0
    assert metrics["vector"]["length_stats"] is None
    assert report["qc_status"] == "ok"


def test_null_attributes_and_invalid_geometry_are_counted():
    metrics = qc_report(str(FIXTURES / "dirty.gpkg"), QcContext())["metrics"]
    assert metrics["vector"]["invalid_count"] == 1
    assert metrics["vector"]["null_counts"]["name"] == 1


def test_ogr_is_the_authority_on_dimensionality():
    flat = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext())["metrics"]["vector"]
    three_d = qc_report(str(FIXTURES / "aoi_3d.gpkg"), QcContext())["metrics"]["vector"]
    assert flat["has_z"] is False
    assert three_d["has_z"] is True


def test_duplicate_ids_are_counted_only_when_a_column_is_named():
    default = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext())["metrics"]["vector"]
    assert default["duplicate_id_count"] is None
    named = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext(id_column="id"))["metrics"]["vector"]
    assert named["duplicate_id_count"] == 0


def test_a_geoparquet_file_uses_the_read_parquet_branch():
    """export --format parquet exists, so QC must read what it writes."""
    report = qc_report(str(FIXTURES / "aoi.parquet"), QcContext())
    assert report["metrics"]["vector"]["feature_count"] == 4
    assert report["metrics"]["crs"] == "EPSG:4326"


def test_a_missing_file_is_a_gis_error():
    with pytest.raises(GisError) as caught:
        qc_report("/nowhere/missing.gpkg", QcContext())
    assert caught.value.code == INPUT_NOT_FOUND
