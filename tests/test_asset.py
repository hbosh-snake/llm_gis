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
