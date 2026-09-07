"""Unreachable and malformed catalogues produce named codes, not stack traces."""

from __future__ import annotations

import json

import pytest
import requests

from llm_gis import stac_fetch
from llm_gis.errors import GisError


class _Response:
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return json.loads(self._body)


def _responds(monkeypatch, status_code: int, body: str) -> None:
    monkeypatch.setattr(
        stac_fetch.requests, "get", lambda *a, **k: _Response(status_code, body)
    )


def test_a_connection_failure_is_catalog_unreachable(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("name or service not known")

    monkeypatch.setattr(stac_fetch.requests, "get", boom)
    with pytest.raises(GisError) as caught:
        stac_fetch.fetch_json("https://nosuch.invalid/catalog.json")
    assert caught.value.code == "CATALOG_UNREACHABLE"


def test_a_timeout_is_catalog_unreachable(monkeypatch):
    def slow(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(stac_fetch.requests, "get", slow)
    with pytest.raises(GisError) as caught:
        stac_fetch.fetch_json("https://slow.invalid/catalog.json")
    assert caught.value.code == "CATALOG_UNREACHABLE"


def test_a_server_error_is_catalog_unreachable(monkeypatch):
    _responds(monkeypatch, 503, "{}")
    with pytest.raises(GisError) as caught:
        stac_fetch.fetch_json("https://example.invalid/catalog.json")
    assert caught.value.code == "CATALOG_UNREACHABLE"


def test_a_404_is_item_not_found(monkeypatch):
    _responds(monkeypatch, 404, "{}")
    with pytest.raises(GisError) as caught:
        stac_fetch.fetch_json("https://example.invalid/items/nope")
    assert caught.value.code == "ITEM_NOT_FOUND"


def test_unparseable_json_is_catalog_malformed(monkeypatch):
    _responds(monkeypatch, 200, "<html>not json</html>")
    with pytest.raises(GisError) as caught:
        stac_fetch.fetch_json("https://example.invalid/catalog.json")
    assert caught.value.code == "CATALOG_MALFORMED"


def test_json_that_is_not_an_object_is_catalog_malformed(monkeypatch):
    _responds(monkeypatch, 200, "[1, 2, 3]")
    with pytest.raises(GisError) as caught:
        stac_fetch.fetch_json("https://example.invalid/catalog.json")
    assert caught.value.code == "CATALOG_MALFORMED"


def test_item_search_conformance_selects_search_mode():
    root = {"conformsTo": ["https://api.stacspec.org/v1.0.0/item-search"]}
    assert stac_fetch.detect_mode(root) == "search"


def test_a_versioned_item_search_conformance_still_selects_search():
    root = {"conformsTo": ["https://api.stacspec.org/v1.1.0-rc.1/item-search"]}
    assert stac_fetch.detect_mode(root) == "search"


def test_no_conformance_means_traversal():
    assert stac_fetch.detect_mode({"type": "Catalog", "id": "static"}) == "traversal"


def test_core_only_conformance_means_traversal():
    root = {"conformsTo": ["https://api.stacspec.org/v1.0.0/core"]}
    assert stac_fetch.detect_mode(root) == "traversal"
