"""The windowed read, against a committed COG. No network in this file."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_gis import raster
from llm_gis.errors import GisError

FIXTURES = Path(__file__).parent / "fixtures"
SCENE = str(FIXTURES / "scene.tif")

# The fixture spans 399960..405080 E, 5094880..5100000 N in EPSG:32632,
# which is roughly 7.707..7.774 E, 46.000..46.047 N in EPSG:4326 (verified with
# pyproj against the committed fixture, not assumed).
INSIDE = (7.72, 46.01, 7.76, 46.03)
OUTSIDE = (2.0, 48.0, 2.1, 48.1)


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))


def test_a_window_reports_both_bboxes_and_the_native_crs():
    result = raster.window(SCENE, bbox=INSIDE)

    assert "32632" in result["crs"]
    assert result["aoi_intersects"] is True
    assert result["bbox_native"]["minx"] > 399000
    assert 7.7 < result["bbox_4326"]["minx"] < 7.8


def test_a_window_measures_the_band_it_was_asked_for():
    result = raster.window(SCENE, bbox=INSIDE)

    band = result["bands"][0]
    assert band["index"] == 1
    assert band["min"] == 1200.0
    assert band["max"] == 1200.0


def test_no_output_writes_no_pixels(tmp_path):
    result = raster.window(SCENE, bbox=INSIDE)

    assert result["output"] is None
    assert not list(tmp_path.rglob("*.tif"))


def test_output_writes_a_cog():
    import json
    from llm_gis.common import run_command, work_root as root

    destination = root() / "outgoing_test.tif"
    result = raster.window(SCENE, bbox=INSIDE, output=str(destination))

    assert result["output"] == str(destination)
    info = json.loads(run_command(["gdalinfo", "-json", str(destination)]))
    assert info["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"] == "COG"


def test_a_reprojected_window_carries_the_requested_crs():
    result = raster.window(SCENE, bbox=INSIDE, t_srs="EPSG:3857")
    assert "3857" in result["crs"]


def test_an_aoi_outside_the_raster_is_a_finding_not_an_error():
    result = raster.window(SCENE, bbox=OUTSIDE)

    assert result["aoi_intersects"] is False
    assert result["bands"] == []
    assert result["output"] is None


def test_a_bbox_in_the_wrong_order_is_refused():
    with pytest.raises(GisError) as error:
        raster.window(SCENE, bbox=(9.0, 46.0, 8.9, 45.9))
    assert error.value.code == "MISSING_ARGUMENT"


DEFAULT_STATS = ["count", "mean", "min", "max", "stdev"]


def _zones_4326(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box

    path = tmp_path / "zones.gpkg"
    gpd.GeoDataFrame(
        {"name": ["left", "right"]},
        geometry=[box(7.72, 46.01, 7.735, 46.02), box(7.745, 46.01, 7.76, 46.02)],
        crs="EPSG:4326",
    ).to_file(path, driver="GPKG")
    return str(path)


def test_zonal_statistics_return_one_row_per_zone(tmp_path):
    result = raster.window(SCENE, bbox=INSIDE, zones=_zones_4326(tmp_path))

    assert len(result["zonal"]) == 2
    assert {row["name"] for row in result["zonal"]} == {"left", "right"}
    assert result["zonal"][0]["mean"] == 1200.0
    assert result["zonal"][0]["count"] > 0


def test_zones_in_a_different_crs_are_reprojected_not_assumed(tmp_path, monkeypatch):
    """The zones arrive in 4326 against a 32632 raster; we reproject before GDAL sees them."""
    seen = []
    real = raster.run_command

    def spy(args, **kwargs):
        seen.append(args)
        return real(args, **kwargs)

    monkeypatch.setattr(raster, "run_command", spy)
    raster.window(SCENE, bbox=INSIDE, zones=_zones_4326(tmp_path))

    reprojections = [a for a in seen if a[0] == "ogr2ogr" and "-t_srs" in a]
    assert reprojections, "zones must be reprojected explicitly, not left to GDAL's warning"


def test_zone_statistics_are_selectable(tmp_path):
    result = raster.window(SCENE, bbox=INSIDE, zones=_zones_4326(tmp_path), zone_stats=["count"])

    assert "count" in result["zonal"][0]
    assert "stdev" not in result["zonal"][0]
