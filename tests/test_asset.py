"""The shared descriptor: what it holds, and what it leaves empty."""

from llm_gis.asset import (
    LOCAL_FILE,
    REMOTE_URI,
    STAC_ASSET,
    Asset,
    Band,
    Column,
    Layer,
    Provenance,
)


def test_a_local_asset_defaults_every_unmeasured_field():
    asset = Asset("/data/incoming/aoi.gpkg", Provenance(LOCAL_FILE, retrieved_at="2026-09-08T00:00:00Z"))

    assert asset.uri == "/data/incoming/aoi.gpkg"
    assert asset.provenance.source_type == LOCAL_FILE
    assert asset.crs is None
    assert asset.bbox is None
    assert asset.record_count is None
    assert asset.layers == []
    assert asset.columns == []
    assert asset.advertised == {}


def test_provenance_fields_are_present_even_when_they_do_not_apply():
    """A None item_id reads correctly; an absent key would force every consumer to guard."""
    provenance = Provenance(LOCAL_FILE)

    assert provenance.catalog_url is None
    assert provenance.item_id is None
    assert provenance.asset_key is None
    assert provenance.content_hash is None


def test_a_stac_asset_carries_claims_without_promoting_them():
    """Nobody has opened this asset, so the measured fields stay empty."""
    asset = Asset(
        "s3://bucket/part-0.parquet",
        Provenance(STAC_ASSET, catalog_url="https://fake.invalid/item.json", item_id="item-1", asset_key="aws"),
        media_type="application/vnd.apache.parquet",
        readable_by=["duckdb"],
        advertised={"num_rows": 5007414, "proj:epsg": 4326},
    )

    assert asset.advertised["num_rows"] == 5007414
    assert asset.record_count is None
    assert asset.crs is None


def test_the_record_types_hold_what_the_producers_emit():
    assert Column("geom", "GEOMETRY").type == "GEOMETRY"
    assert Layer("aoi", "Polygon", 4).feature_count == 4
    assert Band(1, "Float32", -9999.0).nodata == -9999.0


def test_two_assets_do_not_share_mutable_defaults():
    first = Asset("a", Provenance(REMOTE_URI))
    first.roles.append("data")

    assert Asset("b", Provenance(REMOTE_URI)).roles == []


import json
from pathlib import Path

from llm_gis import catalog

FIXTURES = Path(__file__).parent / "fixtures"


def _item():
    """The same recorded item tests/test_stac_shape.py flattens."""
    return json.loads((FIXTURES / "stac" / "overture_item.json").read_text(encoding="utf-8"))


def test_catalog_builds_an_asset_carrying_its_stac_provenance():
    item = _item()
    asset = catalog.build_asset(
        "aws",
        item["assets"]["aws"],
        item["properties"],
        item_url="https://fake.invalid/item.json",
        item_id=item["id"],
    )

    assert asset.uri == item["assets"]["aws"]["href"]
    assert asset.provenance.source_type == STAC_ASSET
    assert asset.provenance.asset_key == "aws"
    assert asset.provenance.item_id == item["id"]
    assert asset.provenance.catalog_url == "https://fake.invalid/item.json"
    assert asset.provenance.content_hash is None


def test_catalog_round_trips_to_the_json_its_callers_already_know():
    item = _item()
    asset = catalog.build_asset("aws", item["assets"]["aws"], item["properties"])

    assert catalog._to_asset_json(asset) == catalog.flatten_asset(
        "aws", item["assets"]["aws"], item["properties"]
    )
    assert set(catalog._to_asset_json(asset)) == {
        "key", "href", "media_type", "roles", "advertised", "readable_by"
    }


from llm_gis import duck

PARQUET = str(FIXTURES / "aoi.parquet")


def test_duck_describe_still_emits_its_historic_keys():
    report = duck.describe(PARQUET)

    assert set(report) == {"uri", "row_count", "columns", "geometry_column", "crs", "bbox"}
    assert report["row_count"] == 4
    assert report["geometry_column"] == "geom"
    assert report["crs"] == "EPSG:4326"


def test_duck_serializer_maps_canonical_names_back():
    asset = duck._build_asset(
        "/tmp/x.parquet",
        [Column("fid", "BIGINT")],
        4,
        "geom",
        {"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0},
        "EPSG:4326",
    )

    assert asset.record_count == 4
    assert asset.provenance.source_type == LOCAL_FILE
    assert duck._to_describe(asset)["row_count"] == 4
    assert duck._to_describe(asset)["columns"] == [{"name": "fid", "type": "BIGINT"}]


def test_duck_marks_a_remote_uri_as_remote():
    asset = duck._build_asset("s3://bucket/part-0.parquet", [], 0, None, None, None)

    assert asset.provenance.source_type == REMOTE_URI


from llm_gis.inspect import inspect_dataset


def test_inspect_vector_still_emits_its_historic_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))
    report = inspect_dataset(FIXTURES / "aoi.gpkg")

    assert set(report) == {
        "dataset_kind", "input_path", "layers", "detected_crs",
        "extent", "crs_status", "crs_reasons", "raw", "created_at",
    }
    assert report["dataset_kind"] == "vector"
    assert report["layers"][0]["feature_count"] == 4
    assert "row_count" not in report
    assert "uri" not in report


def test_inspect_raster_still_emits_its_historic_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))
    report = inspect_dataset(FIXTURES / "elevation.tif")

    assert set(report) == {
        "dataset_kind", "input_path", "size", "bands", "detected_crs",
        "extent", "crs_status", "crs_reasons", "raw", "created_at",
    }
    assert report["size"] == [20, 20]
    assert report["bands"][0]["nodata"] == -9999.0


def test_inspect_leaves_record_count_and_hash_empty(monkeypatch, tmp_path):
    """inspect has only per-layer counts, and describing a file does not hash it."""
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))
    import json as _json

    from llm_gis.common import run_command
    from llm_gis.inspect import _build_vector_asset

    payload = _json.loads(run_command(["ogrinfo", "-json", "-ro", str(FIXTURES / "aoi.gpkg")]))
    asset = _build_vector_asset(FIXTURES / "aoi.gpkg", payload)

    assert asset.record_count is None
    assert asset.layers[0].feature_count == 4
    assert asset.provenance.content_hash is None
    assert asset.provenance.source_type == LOCAL_FILE
