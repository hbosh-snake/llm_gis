"""Every network call Phase 4 makes, and nothing else.

Kept apart from catalog.py so that every output shape can be tested from a
recorded fixture with no network, and so the request budget has one choke point.
"""

from __future__ import annotations

import json
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
