"""Real catalogues over the network. Deselected by default; run with -m live.

These assert the shape of what public catalogues return, not their contents,
which change daily. The one exception is the Example 2 chain, which must
actually produce rows.
"""

from __future__ import annotations

import pytest

from llm_gis.catalog import get_assets, list_collections, search_items
from llm_gis.query import query

OSLO = [10.6, 59.8, 10.9, 60.0]


@pytest.mark.live
def test_overture_is_a_static_catalogue_and_says_so():
    result = list_collections("overture")
    assert result["mode"] == "traversal"
    assert any(c["id"] == "building" for c in result["collections"])


@pytest.mark.live
def test_overture_latest_only_walks_fewer_requests_and_the_same_collections():
    every_release = list_collections("overture")
    newest_release = list_collections("overture", latest_only=True)
    assert {c["id"] for c in newest_release["collections"]} == {c["id"] for c in every_release["collections"]}
    assert newest_release["requests_used"] < every_release["requests_used"]


@pytest.mark.live
def test_cdse_declares_item_search():
    result = search_items("cdse", collection="sentinel-2-l2a", bbox=OSLO, limit=3)
    assert result["mode"] == "search"
    assert result["items_returned"] <= 3
    for item in result["items"]:
        assert item["self"]
        assert item["bbox"]


@pytest.mark.live
def test_a_sentinel_2_asset_has_no_reader_in_this_workspace_yet():
    """Honest about the Phase 7 gap rather than implying a COG is usable."""
    found = search_items("cdse", collection="sentinel-2-l2a", bbox=OSLO, limit=1)
    assets = get_assets(found["items"][0]["self"])["assets"]
    assert assets
    assert all(a["readable_by"] == [] for a in assets)


@pytest.mark.live
def test_example_2_discovery_feeds_duckdb_with_no_ingestion(tmp_path):
    """The phase's done-when: public STAC, GeoParquet href, bbox query, result written."""
    found = search_items("overture", collection="building", bbox=OSLO, limit=1)
    assert found["items_returned"] == 1

    assets = get_assets(found["items"][0]["self"], role="data")["assets"]
    parquet = next(a for a in assets if a["readable_by"] == ["duckdb"])
    assert parquet["href"].startswith("https://")

    output = tmp_path / "buildings.parquet"
    result = query(parquet["href"], bbox=tuple(OSLO), limit=10, output_path=output)

    assert result["engine"] == "duckdb"
    assert result["matched_row_count"] > 0
    assert output.exists()
