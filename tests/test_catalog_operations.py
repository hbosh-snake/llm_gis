"""The four operations, with the network faked at the fetcher seam."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_gis import catalog, stac_fetch
from llm_gis.errors import GisError

FIXTURES = Path(__file__).parent / "fixtures" / "stac"
ROOT = "https://fake.invalid/catalog.json"
COLLECTION = "https://fake.invalid/things/collection.json"
ITEM = "https://fake.invalid/things/0.json"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def static_catalogue(monkeypatch):
    """A static catalogue served from the fixtures, counted at the fetch seam."""
    collection = _load("overture_collection")
    collection["links"] = [
        {"rel": "self", "href": COLLECTION},
        {"rel": "item", "href": ITEM},
    ]
    item = _load("overture_item")
    documents = {
        ROOT: {"type": "Catalog", "id": "root", "links": [{"rel": "child", "href": COLLECTION}]},
        COLLECTION: collection,
        ITEM: item,
    }
    monkeypatch.setattr(stac_fetch, "fetch_json", lambda url: documents[url])
    return documents


def test_search_over_a_static_catalogue_reports_traversal_mode(static_catalogue):
    result = catalog.search_items(ROOT)
    assert result["mode"] == "traversal"
    assert result["catalog"] == ROOT
    assert result["items_returned"] == 1
    assert result["items"][0]["id"] == "00000"
    assert result["truncated"] is False
    assert result["requests_used"] >= 1


def test_search_output_carries_the_self_href_the_item_commands_need(static_catalogue):
    result = catalog.search_items(ROOT)
    assert result["items"][0]["self"].endswith("/00000/00000.json")


def test_listing_collections_over_a_static_catalogue_walks(static_catalogue):
    result = catalog.list_collections(ROOT)
    assert result["mode"] == "traversal"
    assert [c["id"] for c in result["collections"]] == ["building"]
    assert result["collections"][0]["license"] == "ODbL-1.0"


def test_get_item_is_one_fetch_of_a_url(static_catalogue):
    result = catalog.get_item(ITEM)
    assert result["item"]["id"] == "00000"
    assert result["item"]["properties"]["num_rows"] == 5007414


def test_get_assets_lists_every_asset_with_its_readability(static_catalogue):
    result = catalog.get_assets(ITEM)
    keys = sorted(a["key"] for a in result["assets"])
    assert keys == ["aws", "azure"]
    assert all(a["readable_by"] == ["duckdb"] for a in result["assets"])


def test_get_assets_filters_by_role(static_catalogue):
    assert len(catalog.get_assets(ITEM, role="data")["assets"]) == 2
    assert catalog.get_assets(ITEM, role="thumbnail")["assets"] == []


def test_get_assets_filters_by_media_type(static_catalogue):
    result = catalog.get_assets(ITEM, media_type="image/tiff")
    assert result["assets"] == []


def test_a_malformed_item_does_not_crash_the_flattener(monkeypatch):
    monkeypatch.setattr(stac_fetch, "fetch_json", lambda url: _load("malformed_item"))
    with pytest.raises(GisError) as caught:
        catalog.get_assets("https://fake.invalid/bad.json")
    assert caught.value.code == "CATALOG_MALFORMED"


def test_search_mode_flattens_what_the_search_backend_returns(monkeypatch):
    """The search branch, offline: only the backend is faked, not the flattening."""
    response = _load("cdse_search_response")
    monkeypatch.setattr(
        stac_fetch, "fetch_json",
        lambda url: {"conformsTo": ["https://api.stacspec.org/v1.0.0/item-search"]},
    )
    monkeypatch.setattr(
        stac_fetch, "search_api",
        lambda endpoint, **kwargs: {
            "items": response["features"], "collections": [],
            "requests_used": 1, "truncated": False,
        },
    )
    result = catalog.search_items("cdse", collection="sentinel-2-l2a", limit=10)
    assert result["mode"] == "search"
    assert result["items_returned"] == 2
    assert result["items"][0]["properties"]["eo:cloud_cover"] == 37.44
    assert result["items"][1]["self"].endswith("T32VNM")


def test_listing_collections_in_search_mode_uses_the_api_not_a_walk(monkeypatch):
    monkeypatch.setattr(
        stac_fetch, "fetch_json",
        lambda url: {"conformsTo": ["https://api.stacspec.org/v1.0.0/item-search"]},
    )
    monkeypatch.setattr(
        stac_fetch, "list_collections_api",
        lambda endpoint: [_load("overture_collection")],
    )

    def never(*args, **kwargs):
        raise AssertionError("search mode must not walk")

    monkeypatch.setattr(stac_fetch, "traverse", never)
    result = catalog.list_collections("cdse")
    assert result["mode"] == "search"
    assert result["collections"][0]["id"] == "building"


def test_an_unknown_alias_fails_before_any_network(monkeypatch):
    def never(url):
        raise AssertionError("no request should be made")

    monkeypatch.setattr(stac_fetch, "fetch_json", never)
    with pytest.raises(GisError):
        catalog.search_items("nosuchcatalogue")
