"""Regenerate the small committed test fixtures.

Run with: uv run python tests/fixtures/make_fixtures.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import geopandas as gpd
from shapely.geometry import box

FIXTURES_DIR = Path(__file__).parent


def make_aoi_gpkg() -> None:
    polygons = [
        box(10.0, 45.0, 10.1, 45.1),
        box(10.2, 45.0, 10.3, 45.1),
        box(10.0, 45.2, 10.1, 45.3),
        box(10.2, 45.2, 10.3, 45.3),
    ]
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2, 3, 4], "name": ["north", "east", "south", "west"]},
        geometry=polygons,
        crs="EPSG:4326",
    )
    gdf.to_file(FIXTURES_DIR / "aoi.gpkg", driver="GPKG")


def make_elevation_tif() -> None:
    subprocess.run(
        [
            "gdal_create",
            "-outsize",
            "20",
            "20",
            "-bands",
            "1",
            "-ot",
            "Float32",
            "-a_srs",
            "EPSG:4326",
            "-a_ullr",
            "10.0",
            "45.3",
            "10.2",
            "45.1",
            "-a_nodata",
            "-9999",
            "-burn",
            "500",
            str(FIXTURES_DIR / "elevation.tif"),
        ],
        check=True,
    )


if __name__ == "__main__":
    make_aoi_gpkg()
    make_elevation_tif()
