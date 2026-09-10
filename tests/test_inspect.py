import json
from pathlib import Path

import pytest

from llm_gis.errors import INPUT_NOT_FOUND, UNSUPPORTED_FORMAT, GisError
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
    assert report["crs_status"] == "ok"
    assert report["size"] == [20, 20]


def test_inspect_missing_path_raises():
    with pytest.raises(GisError) as excinfo:
        inspect_dataset(FIXTURES / "does-not-exist.gpkg")
    assert excinfo.value.code == INPUT_NOT_FOUND


def test_crs_is_reported_as_an_epsg_code_for_both_kinds(monkeypatch, tmp_path):
    """detected_crs must have one shape; the raster path used to emit raw WKT."""
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))
    vector = inspect_dataset(FIXTURES / "aoi.gpkg")["detected_crs"]
    raster = inspect_dataset(FIXTURES / "elevation.tif")["detected_crs"]
    assert vector == "EPSG:4326"
    assert raster == "EPSG:4326"


def test_inspect_accepts_a_remote_uri_and_prefixes_vsicurl(monkeypatch):
    """No network here: we assert the argv GDAL would have been given."""
    seen = []

    def fake_run_command(args, **kwargs):
        seen.append(args)
        if args[0] == "ogrinfo":
            raise RuntimeError("not a vector")
        return json.dumps(
            {
                "size": [10980, 10980],
                "coordinateSystem": {"wkt": 'PROJCRS["WGS 84 / UTM zone 32N",ID["EPSG",32632]]'},
                "cornerCoordinates": {
                    "lowerLeft": [399960.0, 4990200.0],
                    "upperRight": [509760.0, 5100000.0],
                },
                "bands": [{"band": 1, "type": "UInt16", "noDataValue": 0.0}],
            }
        )

    monkeypatch.setattr("llm_gis.inspect.run_command", fake_run_command)

    report = inspect_dataset("https://example.com/scenes/B04.tif")

    assert report["dataset_kind"] == "raster"
    assert report["input_path"] == "https://example.com/scenes/B04.tif"
    assert seen[-1][-1] == "/vsicurl/https://example.com/scenes/B04.tif"


def test_inspect_missing_remote_uri_is_not_pre_checked(monkeypatch):
    """The .exists() guard is for local paths; a URL cannot be stat-ed."""

    def fake_run_command(args, **kwargs):
        raise RuntimeError("404")

    monkeypatch.setattr("llm_gis.inspect.run_command", fake_run_command)

    with pytest.raises(GisError) as error:
        inspect_dataset("https://example.com/missing.tif")
    assert error.value.code == UNSUPPORTED_FORMAT
