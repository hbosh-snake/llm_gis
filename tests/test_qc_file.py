"""File collectors against the committed fixtures. Offline, given a warm
DuckDB extension cache -- the same caveat tests/test_duck.py carries."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_gis import qc_collect
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


def test_qc_reads_a_raster_through_the_gdal_uri_helper(monkeypatch):
    """A remote raster is a QC source now; assert the argv rather than hit the network."""
    import json as json_module

    seen = []

    def fake_run_command(args, **kwargs):
        seen.append(args)
        return json_module.dumps(
            {
                "size": [10, 10],
                "geoTransform": [0, 10.0, 0, 10, 0, -10.0],
                "coordinateSystem": {"wkt": 'PROJCRS["x",ID["EPSG",32632]]'},
                "cornerCoordinates": {"lowerLeft": [0, 0], "upperRight": [100, 100]},
                "bands": [{"band": 1, "minimum": 1.0, "maximum": 2.0, "noDataValue": None}],
            }
        )

    monkeypatch.setattr("llm_gis.qc_collect.run_command", fake_run_command)

    metrics = qc_collect.file_raster_metrics("https://e.com/B04.tif", False)

    assert metrics["raster"]["width"] == 10
    assert seen[0][-1] == "/vsicurl/https://e.com/B04.tif"


def test_qc_over_a_window_measures_the_window_not_the_scene():
    scene = str(Path(__file__).parent / "fixtures" / "scene.tif")
    whole = qc_collect.file_raster_metrics(scene, True)
    windowed = qc_collect.file_raster_metrics(
        scene, True, bbox={"minx": 7.72, "miny": 46.01, "maxx": 7.735, "maxy": 46.02}
    )

    assert windowed["raster"]["width"] < whole["raster"]["width"]
