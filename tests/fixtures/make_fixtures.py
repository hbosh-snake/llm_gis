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


def make_dirty_gpkg() -> None:
    """One self-intersecting polygon and one null attribute, so invalid_count
    and null_counts see real data rather than zeros."""
    from shapely.geometry import Polygon

    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2], "name": ["ok", None]},
        geometry=[box(10.0, 45.0, 10.1, 45.1), bowtie],
        crs="EPSG:4326",
    )
    gdf.to_file(FIXTURES_DIR / "dirty.gpkg", driver="GPKG")


def make_aoi_3d_gpkg() -> None:
    """Z coordinates, so has_z is exercised against a real 3D layer."""
    from shapely.geometry import Polygon

    ring = [(10.0, 45.0, 100.0), (10.1, 45.0, 100.0), (10.1, 45.1, 100.0), (10.0, 45.0, 100.0)]
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Polygon(ring)], crs="EPSG:4326")
    gdf.to_file(FIXTURES_DIR / "aoi_3d.gpkg", driver="GPKG")


if __name__ == "__main__":
    make_aoi_gpkg()
    make_elevation_tif()
    make_dirty_gpkg()
    make_aoi_3d_gpkg()
