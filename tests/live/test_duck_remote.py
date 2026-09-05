"""Remote GeoParquet over https. Needs network, so it lives with the live suite."""

import pytest

from llm_gis.duck import describe
from llm_gis.query import query

REMOTE = "https://raw.githubusercontent.com/opengeospatial/geoparquet/main/examples/example.parquet"


@pytest.mark.live
def test_describe_a_remote_geoparquet_without_downloading_it():
    report = describe(REMOTE)
    assert report["row_count"] == 5
    assert report["geometry_column"] == "geometry"
    assert report["crs"] == "OGC:CRS84"


@pytest.mark.live
def test_bbox_query_against_a_remote_source_discriminates():
    """The whole point of the engine: fetch only what the AOI needs."""
    east_africa = query(REMOTE, bbox=(29, -12, 41, -1))
    north_america = query(REMOTE, bbox=(-140, 25, -60, 80))
    europe = query(REMOTE, bbox=(-10, 35, 30, 60))
    assert (east_africa["matched_row_count"], north_america["matched_row_count"], europe["matched_row_count"]) == (1, 2, 0)
    assert east_africa["source_row_count"] == 5
