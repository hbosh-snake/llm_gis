from pathlib import Path

import pytest

from llm_gis.inspect import inspect_dataset

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))


def test_inspect_vector_fixture():
    report = inspect_dataset(FIXTURES / "aoi.gpkg")

    assert report["dataset_kind"] == "vector"
    assert report["crs_status"] == "ok"
    assert "4326" in report["detected_crs"]

    extent = report["extent"]
    assert -180 <= extent["minx"] <= extent["maxx"] <= 180
    assert -90 <= extent["miny"] <= extent["maxy"] <= 90

    assert report["layers"][0]["feature_count"] == 4


def test_inspect_raster_fixture():
    report = inspect_dataset(FIXTURES / "elevation.tif")

    assert report["dataset_kind"] == "raster"
    assert len(report["bands"]) == 1
    assert report["bands"][0]["nodata"] == -9999.0
    # crs_status is "suspicious" here, not "ok": inspect_dataset's raster path
    # passes the full WKT to crs_status (no EPSG code extraction, unlike the
    # vector path), and crs_status's projected-CRS heuristic matches the
    # substring "METRE" in the WKT's ellipsoid LENGTHUNIT, which is present
    # in effectively every CRS including geographic ones. See report.
    assert report["crs_status"] == "suspicious"
    assert report["size"] == [20, 20]


def test_inspect_missing_path_raises():
    with pytest.raises(FileNotFoundError):
        inspect_dataset(FIXTURES / "does-not-exist.gpkg")
