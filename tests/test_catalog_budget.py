"""Traversal against a fake fetcher: budgets, cycles and the extent prefilter."""

from __future__ import annotations

import pytest

from llm_gis import stac_fetch
from llm_gis.stac_fetch import Budget, bbox_intersects, matches_datetime, traverse

ROOT = "https://fake.invalid/catalog.json"
COLLECTION = "https://fake.invalid/things/collection.json"


def _item(index: int, bbox: list[float], when: str = "2026-08-19T00:00:00Z") -> dict:
    return {
        "type": "Feature",
        "id": f"{index:05d}",
        "collection": "things",
        "bbox": bbox,
        "properties": {"datetime": when},
        "assets": {},
        "links": [{"rel": "self", "href": f"https://fake.invalid/things/{index}.json"}],
    }


def _catalogue(item_count: int, sub_extents: list[list[float]] | None) -> dict:
    """A static catalogue: root -> one collection -> item_count items."""
    item_links = [
        {"rel": "item", "href": f"https://fake.invalid/things/{i}.json"} for i in range(item_count)
    ]
    bboxes = [[-180.0, -90.0, 180.0, 90.0]] + (sub_extents or [])
    documents = {
        ROOT: {
            "type": "Catalog",
            "id": "root",
            "links": [{"rel": "child", "href": COLLECTION}],
        },
        COLLECTION: {
            "type": "Collection",
            "id": "things",
            "extent": {"spatial": {"bbox": bboxes}},
            "links": [{"rel": "self", "href": COLLECTION}] + item_links,
        },
    }
    for i in range(item_count):
        offset = float(i)
        documents[f"https://fake.invalid/things/{i}.json"] = _item(
            i, [offset, offset, offset + 1, offset + 1]
        )
    return documents


class FakeFetcher:
    """Serves recorded documents and counts every request."""

    def __init__(self, documents: dict) -> None:
        self.documents = documents
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        return self.documents[url]


def test_bbox_intersects_is_inclusive_of_touching_edges():
    assert bbox_intersects([0, 0, 1, 1], [1, 1, 2, 2]) is True
    assert bbox_intersects([0, 0, 1, 1], [2, 2, 3, 3]) is False
    assert bbox_intersects([0, 0, 10, 10], [4, 4, 5, 5]) is True


def test_a_null_bbox_never_filters_anything_out():
    assert bbox_intersects(None, [0, 0, 1, 1]) is True
    assert bbox_intersects([0, 0, 1, 1], None) is True


def test_datetime_matching_handles_a_range_and_an_open_end():
    assert matches_datetime("2026-08-19T00:00:00Z", "2026-01-01/2026-12-31") is True
    assert matches_datetime("2025-08-19T00:00:00Z", "2026-01-01/2026-12-31") is False
    assert matches_datetime("2026-08-19T00:00:00Z", "2026-01-01/..") is True
    assert matches_datetime("2026-08-19T00:00:00Z", "../2026-01-01") is False


def test_no_datetime_spec_matches_everything():
    assert matches_datetime(None, None) is True
    assert matches_datetime("2026-08-19T00:00:00Z", None) is True


def test_an_item_without_a_datetime_is_excluded_when_a_range_is_asked_for():
    """Passing it through unfiltered would be a silent lie about what was checked."""
    assert matches_datetime(None, "2026-01-01/2026-12-31") is False


def test_traversal_finds_items_through_child_links():
    fetcher = FakeFetcher(_catalogue(3, None))
    result = traverse(ROOT, collection=None, bbox=None, datetime_spec=None, limit=100, fetch=fetcher)
    assert [i["id"] for i in result["items"]] == ["00000", "00001", "00002"]
    assert result["truncated"] is False


def test_the_limit_truncates_and_says_so():
    fetcher = FakeFetcher(_catalogue(10, None))
    result = traverse(ROOT, collection=None, bbox=None, datetime_spec=None, limit=4, fetch=fetcher)
    assert len(result["items"]) == 4
    assert result["truncated"] is True


def test_the_request_budget_truncates_rather_than_refusing(monkeypatch):
    monkeypatch.setattr(stac_fetch, "MAX_REQUESTS", 5)
    fetcher = FakeFetcher(_catalogue(50, None))
    result = traverse(ROOT, collection=None, bbox=None, datetime_spec=None, limit=100, fetch=fetcher)
    assert result["truncated"] is True
    assert result["requests_used"] <= 5
    assert len(fetcher.urls) <= 5


def test_the_extent_prefilter_skips_item_fetches():
    """The whole point: one collection.json instead of every item JSON."""
    sub_extents = [[float(i), float(i), float(i) + 1, float(i) + 1] for i in range(10)]
    fetcher = FakeFetcher(_catalogue(10, sub_extents))
    result = traverse(
        ROOT, collection=None, bbox=[0.0, 0.0, 1.5, 1.5], datetime_spec=None, limit=100, fetch=fetcher
    )
    item_fetches = [u for u in fetcher.urls if u.startswith("https://fake.invalid/things/") and u != COLLECTION]
    assert len(item_fetches) == 2
    assert {i["id"] for i in result["items"]} == {"00000", "00001"}


def test_a_collection_without_sub_extents_still_works_just_more_expensively():
    fetcher = FakeFetcher(_catalogue(4, None))
    result = traverse(
        ROOT, collection=None, bbox=[0.0, 0.0, 1.5, 1.5], datetime_spec=None, limit=100, fetch=fetcher
    )
    assert {i["id"] for i in result["items"]} == {"00000", "00001"}


def test_a_cycle_in_child_links_terminates():
    documents = {
        ROOT: {"type": "Catalog", "id": "a", "links": [{"rel": "child", "href": "https://fake.invalid/b.json"}]},
        "https://fake.invalid/b.json": {
            "type": "Catalog", "id": "b", "links": [{"rel": "child", "href": ROOT}],
        },
    }
    fetcher = FakeFetcher(documents)
    result = traverse(ROOT, collection=None, bbox=None, datetime_spec=None, limit=100, fetch=fetcher)
    assert result["items"] == []
    assert len(fetcher.urls) == 2


def test_an_unmatched_collection_is_never_descended():
    fetcher = FakeFetcher(_catalogue(5, None))
    result = traverse(
        ROOT, collection="somethingelse", bbox=None, datetime_spec=None, limit=100, fetch=fetcher
    )
    assert result["items"] == []
    assert COLLECTION in fetcher.urls
    assert not [u for u in fetcher.urls if u.endswith("/things/0.json")]


def test_the_budget_object_reports_exhaustion():
    budget = Budget(max_requests=2)
    assert budget.spend() is True
    assert budget.spend() is True
    assert budget.spend() is False
    assert budget.used == 2
