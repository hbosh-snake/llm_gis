"""catalog-search --bbox is WGS84; duck-query --bbox is the source's native CRS.

Same flag name, different meaning. This test builds a GeoParquet source in a
projected CRS, takes a WGS84 bbox (what catalog-search would hand back) and
shows it silently matches nothing when passed straight to duck-query, then
shows the fix: reproject the bbox to the source CRS first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_gis.common import reproject_bbox
from llm_gis.duck import connect, describe
from llm_gis.query import query

NATIVE_CRS = "EPSG:32632"  # UTM zone 32N, metres
WGS84_BBOX = (9.0, 45.0, 9.1, 45.1)  # what catalog-search --bbox would return


@pytest.fixture
def utm_parquet(tmp_path) -> Path:
    """A single feature around 9E/45N, stored in its native UTM CRS."""
    path = tmp_path / "utm.parquet"
    connect().execute(
        f"""
        COPY (
          SELECT 1 AS id, ST_SetCRS(
            ST_Transform(
              ST_GeomFromText('POLYGON((9.0 45.0, 9.1 45.0, 9.1 45.1, 9.0 45.1, 9.0 45.0))'),
              'EPSG:4326', '{NATIVE_CRS}', true
            ), '{NATIVE_CRS}'
          ) AS geom
        ) TO '{path}' (FORMAT PARQUET)
        """
    )
    return path


def test_source_is_in_its_native_projected_crs(utm_parquet):
    assert describe(str(utm_parquet))["crs"] == NATIVE_CRS


def test_a_wgs84_bbox_from_catalog_search_matches_nothing_when_used_directly(utm_parquet):
    """The footgun: a lon/lat bbox looks like small, valid numbers next to UTM
    metre coordinates (in the millions), so this fails silently rather than
    erroring."""
    result = query(str(utm_parquet), bbox=WGS84_BBOX)
    assert result["matched_row_count"] == 0


def test_reprojecting_the_bbox_to_the_source_crs_finds_the_feature(utm_parquet):
    wgs84_bbox = {"minx": WGS84_BBOX[0], "miny": WGS84_BBOX[1], "maxx": WGS84_BBOX[2], "maxy": WGS84_BBOX[3]}
    native_bbox = reproject_bbox(wgs84_bbox, "EPSG:4326", NATIVE_CRS)
    result = query(
        str(utm_parquet),
        bbox=(native_bbox["minx"], native_bbox["miny"], native_bbox["maxx"], native_bbox["maxy"]),
    )
    assert result["matched_row_count"] == 1
