"""Every network call Phase 4 makes, and nothing else.

Kept apart from catalog.py so that every output shape can be tested from a
recorded fixture with no network, and so the request budget has one choke point.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import requests

from llm_gis.errors import (
    CATALOG_MALFORMED,
    CATALOG_UNREACHABLE,
    ITEM_NOT_FOUND,
    GisError,
)

TIMEOUT_SECONDS = 30
ITEM_SEARCH_CONFORMANCE = "/item-search"


def fetch_json(url: str) -> dict[str, Any]:
    """One GET returning a STAC document. No retries: a flaky catalogue says so."""
    try:
        response = requests.get(url, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as error:
        raise GisError(
            CATALOG_UNREACHABLE,
            f"Could not reach {url}",
            "Check the catalogue URL and that the agent container has network egress",
            {"error": str(error)},
        ) from error

    if response.status_code == 404:
        raise GisError(
            ITEM_NOT_FOUND,
            f"No STAC document at {url}",
            "Check the item URL, which catalog-search returns as the 'self' field",
        )
    if response.status_code >= 400:
        raise GisError(
            CATALOG_UNREACHABLE,
            f"{url} returned HTTP {response.status_code}",
            "The catalogue is refusing or failing; try again or use another endpoint",
            {"status_code": response.status_code},
        )

    try:
        document = response.json()
    except (json.JSONDecodeError, ValueError) as error:
        raise GisError(
            CATALOG_MALFORMED,
            f"{url} returned a 200 that is not JSON",
            "Confirm the URL points at a STAC document rather than a web page",
            {"error": str(error)},
        ) from error

    if not isinstance(document, dict):
        raise GisError(
            CATALOG_MALFORMED,
            f"{url} returned JSON that is not a STAC document",
            "A STAC catalog, collection or item is a JSON object",
        )
    return document


def detect_mode(root: dict[str, Any]) -> str:
    """'search' when the catalogue declares Item Search, otherwise 'traversal'."""
    conforms = root.get("conformsTo") or []
    return "search" if any(ITEM_SEARCH_CONFORMANCE in c for c in conforms) else "traversal"


MAX_REQUESTS = 200
MAX_DEPTH = 5


class Budget:
    """A request allowance. Spending past it truncates; it never raises."""

    def __init__(self, max_requests: int) -> None:
        self.max_requests = max_requests
        self.used = 0
        self.truncated = False

    def spend(self) -> bool:
        """True if a request may be made, False once the allowance is gone."""
        if self.used >= self.max_requests:
            self.truncated = True
            return False
        self.used += 1
        return True


def bbox_intersects(a: list[float] | None, b: list[float] | None) -> bool:
    """Rectangle overlap in lon/lat. A missing bbox filters nothing out."""
    if not a or not b:
        return True
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _parse(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def matches_datetime(value: str | None, spec: str | None) -> bool:
    """RFC 3339 instant against a STAC range. No spec matches everything.

    An item with no datetime is excluded whenever a range is asked for: passing
    it through would claim a check that did not happen.
    """
    if spec is None:
        return True
    if value is None:
        return False
    moment = _parse(value)
    start_text, separator, end_text = spec.partition("/")
    if not separator:
        return moment == _parse(start_text)
    if start_text not in ("..", "") and moment < _parse(start_text):
        return False
    if end_text not in ("..", "") and moment > _parse(end_text):
        return False
    return True


def _sub_extents(collection: dict) -> list[list[float]]:
    bboxes = ((collection.get("extent") or {}).get("spatial") or {}).get("bbox") or []
    return list(bboxes[1:])


def _prefilter_allows(collection: dict, bbox: list[float] | None) -> bool:
    """False when the collection's advertised sub-extents all miss the bbox."""
    if bbox is None:
        return True
    extents = _sub_extents(collection)
    if not extents:
        return True
    return any(bbox_intersects(extent, bbox) for extent in extents)


def _links(document: dict, rel: str) -> list[str]:
    return [l["href"] for l in document.get("links") or [] if l.get("rel") == rel and l.get("href")]


def traverse(
    root_url: str,
    *,
    collection: str | None,
    bbox: list[float] | None,
    datetime_spec: str | None,
    limit: int,
    fetch=None,
) -> dict:
    """Walk a static catalogue under a request budget, filtering client-side.

    'fetch' is resolved at call time, not bound as a default, so a test can
    replace fetch_json on the module and have the walk actually use it.
    """
    fetch = fetch or fetch_json
    budget = Budget(MAX_REQUESTS)
    seen: set[str] = set()
    collections: list[dict] = []
    items: list[dict] = []

    def walk(url: str, depth: int) -> None:
        if url in seen or depth > MAX_DEPTH or (limit and len(items) >= limit):
            return
        seen.add(url)
        if not budget.spend():
            return
        document = fetch(url)

        if document.get("type") == "Collection":
            collections.append(document)
            if collection is not None and document.get("id") != collection:
                return
            if not _prefilter_allows(document, bbox):
                return
            _collect_items(document, bbox)
            return

        for child in _links(document, "child"):
            walk(child, depth + 1)

    def _collect_items(document: dict, box: list[float] | None) -> None:
        if not limit:  # a collections-only walk, as list_collections asks for
            return
        extents = _sub_extents(document)
        hrefs = _links(document, "item")
        for index, href in enumerate(hrefs):
            if len(items) >= limit:
                budget.truncated = True
                return
            if box is not None and index < len(extents) and not bbox_intersects(extents[index], box):
                continue
            if href in seen:
                continue
            seen.add(href)
            if not budget.spend():
                return
            item = fetch(href)
            if not bbox_intersects(item.get("bbox"), box):
                continue
            if not matches_datetime((item.get("properties") or {}).get("datetime"), datetime_spec):
                continue
            items.append(item)

    walk(root_url, 0)
    return {
        "items": items,
        "collections": collections,
        "requests_used": budget.used,
        "truncated": budget.truncated,
    }


def search_api(
    endpoint: str,
    *,
    collection: str | None,
    bbox: list[float] | None,
    datetime_spec: str | None,
    limit: int,
) -> dict:
    """Server-side item search. pystac-client objects stay inside this function."""
    from pystac_client import Client

    client = Client.open(endpoint)
    search = client.search(
        collections=[collection] if collection else None,
        bbox=bbox,
        datetime=datetime_spec,
        max_items=limit,
    )
    items = list(search.items_as_dicts())
    return {
        "items": items,
        "collections": [],
        "requests_used": 1,
        "truncated": len(items) >= limit,
    }


def list_collections_api(endpoint: str) -> list[dict]:
    """Collection documents from a search API's /collections endpoint."""
    from pystac_client import Client

    return [c.to_dict() for c in Client.open(endpoint).get_collections()]
