"""Flatteners over recorded STAC JSON. Pure functions, no network."""

from __future__ import annotations

import json
from pathlib import Path

from llm_gis.catalog import flatten_asset, flatten_collection, flatten_item, readable_by

FIXTURES = Path(__file__).parent / "fixtures" / "stac"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_an_item_flattens_to_the_documented_keys():
    flat = flatten_item(_load("overture_item"))
    assert flat["id"] == "00000"
    assert flat["collection"] == "building"
    assert flat["self"].endswith("/00000/00000.json")
    assert flat["bbox"][0] == -180.0
    assert flat["datetime"] == "2026-08-19T00:00:00Z"
    assert flat["asset_count"] == 2


def test_item_properties_pass_through_verbatim():
    """A whitelist would drop the field that mattered for an unfamiliar collection."""
    overture = flatten_item(_load("overture_item"))
    cdse = flatten_item(_load("cdse_item"))
    assert overture["properties"]["num_rows"] == 5007414
    assert cdse["properties"]["eo:cloud_cover"] == 37.44
    assert cdse["properties"]["proj:epsg"] == 32632


def test_a_missing_optional_field_is_null_not_absent():
    """An absent key and a null read the same to a caller; emit the key."""
    flat = flatten_item({"id": "x", "type": "Feature", "properties": {}, "assets": {}})
    assert flat["bbox"] is None
    assert flat["datetime"] is None
    assert flat["self"] is None
    assert flat["collection"] is None


def test_a_geoparquet_asset_is_readable_by_duckdb():
    item = _load("overture_item")
    flat = flatten_asset("aws", item["assets"]["aws"], item["properties"])
    assert flat["key"] == "aws"
    assert flat["media_type"] == "application/vnd.apache.parquet"
    assert flat["roles"] == ["data"]
    assert flat["readable_by"] == ["duckdb"]


def test_a_raster_asset_is_readable_by_nothing_yet():
    """A COG href is a dead end until Phase 7, and must say so rather than imply otherwise."""
    item = _load("cdse_item")
    flat = flatten_asset("B04_10m", item["assets"]["B04_10m"], item["properties"])
    assert flat["readable_by"] == []
    assert flat["advertised"]["size_bytes"] == 123456789


def test_advertised_metadata_is_namespaced_away_from_measurements():
    item = _load("overture_item")
    flat = flatten_asset("aws", item["assets"]["aws"], item["properties"])
    assert flat["advertised"]["num_rows"] == 5007414
    assert flat["advertised"]["size_bytes"] is None
    assert "num_rows" not in flat


def test_readable_by_maps_only_parquet_media_types():
    assert readable_by("application/vnd.apache.parquet") == ["duckdb"]
    assert readable_by("application/x-parquet") == ["duckdb"]
    assert readable_by("image/tiff; application=geotiff; profile=cloud-optimized") == []
    assert readable_by(None) == []


def test_a_collection_flattens_with_its_sub_extents_kept():
    flat = flatten_collection(_load("overture_collection"))
    assert flat["id"] == "building"
    assert flat["license"] == "ODbL-1.0"
    assert flat["bbox"] == [-180.0, -90.0, 180.0, 90.0]
    assert len(flat["sub_extents"]) == 2
