"""Example 3, against a live Earth Search COG. Excluded from the default run.

Run with: bin/test tests/live/test_raster_remote.py -m live -v
"""

from __future__ import annotations

import pytest

from llm_gis import raster
from llm_gis.inspect import inspect_dataset

HREF = (
    "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/"
    "32/T/MR/2023/6/S2A_32TMR_20230605_0_L2A/B04.tif"
)
AOI = (8.90, 45.95, 8.96, 46.00)

pytestmark = pytest.mark.live


def test_remote_inspect_reads_the_header_only():
    report = inspect_dataset(HREF)

    assert report["dataset_kind"] == "raster"
    assert report["size"] == [10980, 10980]
    assert "32632" in report["detected_crs"]


def test_a_window_read_does_not_download_the_scene(tmp_path):
    destination = tmp_path / "aoi.tif"
    result = raster.window(HREF, bbox=AOI, stats=True, output=str(destination))

    assert result["aoi_intersects"] is True
    assert result["bands"][0]["mean"] is not None
    # The scene is roughly 150 MB; the window is a small fraction of it.
    assert destination.stat().st_size < 5_000_000
