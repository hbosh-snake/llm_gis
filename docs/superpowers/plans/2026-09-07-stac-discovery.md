# STAC Discovery (Phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator discover remote datasets in public STAC catalogues and hand a GeoParquet asset href straight to `duck-query`, without downloading or ingesting anything.

**Architecture:** Two modules split on a pure/IO seam. `llm_gis/catalog.py` holds endpoint aliases, the four public operations and the flatteners that turn STAC JSON into plain dicts; `llm_gis/stac_fetch.py` holds every network call, conformance detection, and the two discovery backends. Catalogues that declare STAC API Item Search are queried server-side through `pystac-client`; static catalogues are walked with a plain JSON fetcher under an explicit request budget. Traversal is implemented directly rather than through `pystac-client`'s recursive helpers so the request budget stays honest and the walk is testable against a fake fetcher.

**Tech Stack:** Python 3.12, `uv`, Typer, `pystac-client>=0.9`, pytest. Existing `llm_gis/errors.py` contract, existing `bin/*` wrapper idiom.

**Spec:** `docs/superpowers/specs/2026-09-07-stac-discovery-design.md`

## Global Constraints

- Package manager is `uv`. `uv add <pkg>`, `uv run <cmd>`. Never `pip`, never `python3`.
- Existing command names, flags and JSON field names keep working. Additive changes only.
- No emojis in code. Short modules, short functions, docstrings over inline comments.
- Do not program defensively. No retry logic. HTTP timeout is 30 seconds.
- Tests must pass with no network. Live tests live in `tests/live/`, carry `@pytest.mark.live`, and are deselected by the default `addopts = "-m 'not live'"`.
- Every command prints one JSON object on stdout via `cli._emit`, which adds `status` and `command`. Errors are `GisError`, rendered on stderr with exit 1.
- Missing optional fields are emitted as `null`, never omitted.
- Discovery never downloads an asset, never stages, never ingests, never touches PostGIS.
- `pystac-client` objects never leave `stac_fetch.py`.
- Every `bin/*` command must appear in `docs/llm/OUTPUT_SCHEMA.md` or `tests/test_output_contract.py::test_output_schema_lists_every_bin_command` fails.

---

### Task 1: Dependency, error codes and endpoint aliases

The smallest useful slice: the package is installed, the three new error codes exist, and a catalogue name resolves to a URL.

**Files:**
- Modify: `pyproject.toml` (dependency)
- Modify: `llm_gis/errors.py`
- Create: `llm_gis/catalog.py`
- Create: `tests/test_catalog_aliases.py`

**Interfaces:**
- Consumes: `llm_gis.errors.GisError`
- Produces: `catalog.CATALOGS: dict[str, str]`, `catalog.resolve_endpoint(catalog: str) -> str`, and the error code constants `CATALOG_UNREACHABLE`, `CATALOG_MALFORMED`, `ITEM_NOT_FOUND`

- [ ] **Step 1: Add the dependency**

```bash
uv add "pystac-client>=0.9"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_catalog_aliases.py`:

```python
"""An alias or a URL, and nothing in between."""

from __future__ import annotations

import pytest

from llm_gis.catalog import CATALOGS, resolve_endpoint
from llm_gis.errors import GisError


def test_a_known_alias_resolves_to_its_url():
    assert resolve_endpoint("overture") == "https://stac.overturemaps.org/catalog.json"


def test_every_alias_is_an_https_url():
    for name, url in CATALOGS.items():
        assert url.startswith("https://"), name


def test_a_url_passes_through_unchanged():
    url = "https://example.invalid/stac/v1/"
    assert resolve_endpoint(url) == url


def test_an_unknown_bare_name_is_a_gis_error_naming_the_known_ones():
    with pytest.raises(GisError) as caught:
        resolve_endpoint("nosuchcatalogue")
    assert caught.value.code == "INPUT_NOT_FOUND"
    assert "overture" in caught.value.suggested_action
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `uv run pytest tests/test_catalog_aliases.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'llm_gis.catalog'`

- [ ] **Step 4: Add the three error codes**

In `llm_gis/errors.py`, after the existing `UNEXPECTED = "UNEXPECTED"` line:

```python
CATALOG_UNREACHABLE = "CATALOG_UNREACHABLE"
CATALOG_MALFORMED = "CATALOG_MALFORMED"
ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
```

- [ ] **Step 5: Write the minimal implementation**

Create `llm_gis/catalog.py`:

```python
"""STAC discovery: what is out there, and what can read it.

Never downloads an asset. The output is hrefs plus the metadata the
publisher advertises, so a caller can decide what is worth opening.
"""

from __future__ import annotations

from llm_gis.errors import INPUT_NOT_FOUND, GisError

CATALOGS = {
    "overture": "https://stac.overturemaps.org/catalog.json",
    "cdse": "https://stac.dataspace.copernicus.eu/v1/",
    "earth-search": "https://earth-search.aws.element84.com/v1/",
}


def resolve_endpoint(catalog: str) -> str:
    """An alias from CATALOGS, or any URL passed through unchanged."""
    if catalog.startswith(("http://", "https://")):
        return catalog
    if catalog in CATALOGS:
        return CATALOGS[catalog]
    raise GisError(
        INPUT_NOT_FOUND,
        f"No catalogue named {catalog}",
        f"Use a full https URL, or one of: {', '.join(sorted(CATALOGS))}",
    )
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_catalog_aliases.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock llm_gis/errors.py llm_gis/catalog.py tests/test_catalog_aliases.py
git commit -m "feat(catalog): pystac-client dependency, STAC error codes and endpoint aliases"
```

---

### Task 2: Recorded fixtures and the flatteners

The heart of the phase's testability. Every output field is produced by a pure function over recorded JSON, so no test below this line needs a network.

**Files:**
- Create: `tests/fixtures/stac/overture_item.json`
- Create: `tests/fixtures/stac/overture_collection.json`
- Create: `tests/fixtures/stac/cdse_item.json`
- Create: `tests/fixtures/stac/cdse_search_response.json`
- Create: `tests/fixtures/stac/malformed_item.json`
- Modify: `llm_gis/catalog.py`
- Create: `tests/test_stac_shape.py`

**Interfaces:**
- Consumes: `catalog.resolve_endpoint` (Task 1)
- Produces: `catalog.readable_by(media_type: str | None) -> list[str]`, `catalog.flatten_item(item: dict) -> dict`, `catalog.flatten_asset(key: str, asset: dict, properties: dict) -> dict`, `catalog.flatten_collection(collection: dict) -> dict`

- [ ] **Step 1: Record the fixtures**

These are recordings of real responses, trimmed. Create `tests/fixtures/stac/overture_item.json`:

```json
{
  "type": "Feature",
  "stac_version": "1.1.0",
  "id": "00000",
  "collection": "building",
  "bbox": [-180.0, -84.29460906982422, -86.84698486328125, 14.345832824707031],
  "properties": {
    "num_rows": 5007414,
    "num_row_groups": 256,
    "datetime": "2026-08-19T00:00:00Z"
  },
  "links": [
    {"rel": "self", "href": "https://stac.overturemaps.org/2026-08-19.0/buildings/building/00000/00000.json"}
  ],
  "assets": {
    "aws": {
      "href": "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=buildings/type=building/part-00000-c000.zstd.parquet",
      "type": "application/vnd.apache.parquet",
      "roles": ["data"]
    },
    "azure": {
      "href": "https://overturemapswestus2.blob.core.windows.net/release/2026-08-19.0/theme=buildings/type=building/part-00000-c000.zstd.parquet",
      "type": "application/vnd.apache.parquet",
      "roles": ["data"]
    }
  }
}
```

Create `tests/fixtures/stac/cdse_item.json`:

```json
{
  "type": "Feature",
  "stac_version": "1.1.0",
  "id": "S2C_MSIL2A_20260906T104621_N0512_R051_T32VNM",
  "collection": "sentinel-2-l2a",
  "bbox": [10.2, 60.0, 11.9, 61.0],
  "properties": {
    "datetime": "2026-09-06T10:46:21Z",
    "eo:cloud_cover": 37.44,
    "proj:epsg": 32632
  },
  "links": [
    {"rel": "self", "href": "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/S2C_MSIL2A_20260906T104621_N0512_R051_T32VNM"}
  ],
  "assets": {
    "B04_10m": {
      "href": "s3://eodata/Sentinel-2/MSI/L2A/2026/09/06/B04_10m.jp2",
      "type": "image/jp2",
      "roles": ["data", "reflectance"],
      "file:size": 123456789
    },
    "thumbnail": {
      "href": "https://example.invalid/preview.jpg",
      "type": "image/jpeg",
      "roles": ["thumbnail"]
    }
  }
}
```

Create `tests/fixtures/stac/overture_collection.json`. The `extent.spatial.bbox` array is the point of this fixture: element 0 is the overall extent, elements 1..n are per-item sub-extents.

```json
{
  "type": "Collection",
  "stac_version": "1.1.0",
  "id": "building",
  "title": "building",
  "description": "Overture building footprints",
  "license": "ODbL-1.0",
  "extent": {
    "spatial": {"bbox": [[-180.0, -90.0, 180.0, 90.0], [-180.0, -84.3, -86.8, 14.4], [10.0, 59.0, 12.0, 62.0]]},
    "temporal": {"interval": [["2026-08-19T00:00:00Z", null]]}
  },
  "links": [
    {"rel": "self", "href": "https://stac.overturemaps.org/2026-08-19.0/buildings/building/collection.json"},
    {"rel": "item", "href": "https://stac.overturemaps.org/2026-08-19.0/buildings/building/00000/00000.json"},
    {"rel": "item", "href": "https://stac.overturemaps.org/2026-08-19.0/buildings/building/00001/00001.json"}
  ]
}
```

Create `tests/fixtures/stac/cdse_search_response.json` — a trimmed `/search` response, the shape the search backend returns raw items in:

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "S2C_MSIL2A_20260906T104621_N0512_R051_T32VNM",
      "collection": "sentinel-2-l2a",
      "bbox": [10.2, 60.0, 11.9, 61.0],
      "properties": {"datetime": "2026-09-06T10:46:21Z", "eo:cloud_cover": 37.44},
      "links": [{"rel": "self", "href": "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/S2C_MSIL2A_20260906T104621_N0512_R051_T32VNM"}],
      "assets": {}
    },
    {
      "type": "Feature",
      "id": "S2B_MSIL2A_20260904T104619_N0512_R051_T32VNM",
      "collection": "sentinel-2-l2a",
      "bbox": [10.2, 60.0, 11.9, 61.0],
      "properties": {"datetime": "2026-09-04T10:46:19Z", "eo:cloud_cover": 5.4},
      "links": [{"rel": "self", "href": "https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a/items/S2B_MSIL2A_20260904T104619_N0512_R051_T32VNM"}],
      "assets": {}
    }
  ]
}
```

Create `tests/fixtures/stac/malformed_item.json` — valid JSON, not valid STAC (no `id`, no `type`):

```json
{"hello": "world", "assets": "not-an-object"}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_stac_shape.py`:

```python
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
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `uv run pytest tests/test_stac_shape.py -v`
Expected: FAIL, `ImportError: cannot import name 'flatten_asset'`

- [ ] **Step 4: Write the flatteners**

Append to `llm_gis/catalog.py`:

```python
PARQUET_MEDIA_TYPES = {
    "application/vnd.apache.parquet",
    "application/x-parquet",
    "application/parquet",
}

ADVERTISED_PROPERTIES = ("num_rows", "eo:cloud_cover", "proj:epsg")


def readable_by(media_type: str | None) -> list[str]:
    """Which engine can open this media type. A format fact, not a routing decision.

    Phase 6's planner subsumes this. It must not grow a second opinion here.
    """
    return ["duckdb"] if media_type in PARQUET_MEDIA_TYPES else []


def _self_href(document: dict) -> str | None:
    for link in document.get("links") or []:
        if link.get("rel") == "self":
            return link.get("href")
    return None


def flatten_item(item: dict) -> dict:
    """A STAC item as a flat dict. Properties pass through verbatim."""
    properties = item.get("properties") or {}
    return {
        "id": item.get("id"),
        "collection": item.get("collection"),
        "self": _self_href(item),
        "bbox": item.get("bbox"),
        "datetime": properties.get("datetime"),
        "properties": properties,
        "asset_count": len(item.get("assets") or {}),
    }


def flatten_asset(key: str, asset: dict, properties: dict) -> dict:
    """One asset, with the publisher's claims quarantined under 'advertised'."""
    advertised = {"size_bytes": asset.get("file:size")}
    for name in ADVERTISED_PROPERTIES:
        if name in properties:
            advertised[name] = properties[name]
    return {
        "key": key,
        "href": asset.get("href"),
        "media_type": asset.get("type"),
        "roles": asset.get("roles") or [],
        "advertised": advertised,
        "readable_by": readable_by(asset.get("type")),
    }


def flatten_collection(collection: dict) -> dict:
    """A STAC collection, keeping the per-item sub-extents traversal prefilters on."""
    bboxes = ((collection.get("extent") or {}).get("spatial") or {}).get("bbox") or []
    return {
        "id": collection.get("id"),
        "title": collection.get("title"),
        "description": collection.get("description"),
        "license": collection.get("license"),
        "self": _self_href(collection),
        "bbox": bboxes[0] if bboxes else None,
        "sub_extents": list(bboxes[1:]),
    }
```

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_stac_shape.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/stac llm_gis/catalog.py tests/test_stac_shape.py
git commit -m "feat(catalog): STAC flatteners over recorded fixtures"
```

---

### Task 3: The JSON fetcher and mode detection

Every network call in the phase goes through one function, so the three error codes have one place to be raised and one place to be tested.

**Files:**
- Create: `llm_gis/stac_fetch.py`
- Create: `tests/test_catalog_errors.py`

**Interfaces:**
- Consumes: `errors.CATALOG_UNREACHABLE`, `errors.CATALOG_MALFORMED`, `errors.ITEM_NOT_FOUND` (Task 1)
- Produces: `stac_fetch.TIMEOUT_SECONDS: int`, `stac_fetch.fetch_json(url: str) -> dict`, `stac_fetch.detect_mode(root: dict) -> str`, `stac_fetch.ITEM_SEARCH_CONFORMANCE: str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog_errors.py`:

```python
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
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_catalog_errors.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'llm_gis.stac_fetch'`

- [ ] **Step 3: Write the fetcher**

Create `llm_gis/stac_fetch.py`:

```python
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
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_catalog_errors.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add llm_gis/stac_fetch.py tests/test_catalog_errors.py
git commit -m "feat(catalog): STAC JSON fetcher with named failures and mode detection"
```

---

### Task 4: Budgeted traversal with the extent prefilter

The one way this phase can hurt someone is an unbounded walk. Everything here is tested against a fake fetcher, so the budget, the cycle protection and the prefilter's saving are asserted rather than assumed.

**Files:**
- Modify: `llm_gis/stac_fetch.py`
- Create: `tests/test_catalog_budget.py`

**Interfaces:**
- Consumes: `stac_fetch.fetch_json` (Task 3)
- Produces: `stac_fetch.MAX_REQUESTS: int`, `stac_fetch.MAX_DEPTH: int`, `stac_fetch.Budget`, `stac_fetch.bbox_intersects(a, b) -> bool`, `stac_fetch.matches_datetime(value: str | None, spec: str | None) -> bool`, `stac_fetch.traverse(root_url: str, *, collection: str | None, bbox: list[float] | None, datetime_spec: str | None, limit: int, fetch=None) -> dict` (`fetch` defaults to `fetch_json`, resolved inside the call)

The `traverse` return shape is `{"items": [<raw STAC item dicts>], "collections": [<raw collection dicts>], "requests_used": int, "truncated": bool}`. Raw, not flattened: `catalog.py` owns flattening.

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog_budget.py`:

```python
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
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_catalog_budget.py -v`
Expected: FAIL, `ImportError: cannot import name 'Budget'`

- [ ] **Step 3: Implement the traversal**

Append to `llm_gis/stac_fetch.py`:

```python
from datetime import datetime, timezone

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
```

Move the `from datetime import ...` line up beside the other imports at the top of the file rather than leaving it mid-module.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_catalog_budget.py -v`
Expected: 13 passed

- [ ] **Step 5: Run the whole offline suite for regressions**

Run: `uv run pytest`
Expected: all pass, live tests deselected

- [ ] **Step 6: Commit**

```bash
git add llm_gis/stac_fetch.py tests/test_catalog_budget.py
git commit -m "feat(catalog): budgeted static traversal with extent prefilter"
```

---

### Task 5: The search backend and the four operations

Wires the two backends behind one interface, so `catalog.py` exposes four operations that behave the same whichever kind of catalogue they were pointed at.

**Files:**
- Modify: `llm_gis/stac_fetch.py`
- Modify: `llm_gis/catalog.py`
- Create: `tests/test_catalog_operations.py`

**Interfaces:**
- Consumes: `stac_fetch.fetch_json`, `stac_fetch.detect_mode`, `stac_fetch.traverse` (Tasks 3, 4); `catalog.flatten_item`, `catalog.flatten_asset`, `catalog.flatten_collection`, `catalog.resolve_endpoint` (Tasks 1, 2)
- Produces: `stac_fetch.search_api(endpoint, *, collection, bbox, datetime_spec, limit) -> dict`, and on `catalog`: `list_collections(catalog) -> dict`, `search_items(catalog, *, collection=None, bbox=None, datetime_spec=None, limit=100) -> dict`, `get_item(item_url) -> dict`, `get_assets(item_url, *, role=None, media_type=None) -> dict`

- [ ] **Step 1: Write the failing test**

Create `tests/test_catalog_operations.py`:

```python
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
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_catalog_operations.py -v`
Expected: FAIL, `AttributeError: module 'llm_gis.catalog' has no attribute 'search_items'`

- [ ] **Step 3: Add the search backend**

Append to `llm_gis/stac_fetch.py`:

```python
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
```

- [ ] **Step 4: Add the four operations**

Append to `llm_gis/catalog.py`, and add `from llm_gis import stac_fetch` to its imports:

```python
DEFAULT_LIMIT = 100


def _require_stac(document: dict, url: str) -> dict:
    """A 200 that parsed is not yet a STAC document."""
    if not document.get("id") or not document.get("type"):
        raise GisError(
            CATALOG_MALFORMED,
            f"{url} is JSON but not a STAC document",
            "A STAC item has an 'id' and a 'type'; check the URL",
        )
    return document


def _mode_for(endpoint: str) -> str:
    return stac_fetch.detect_mode(stac_fetch.fetch_json(endpoint))


def list_collections(catalog: str) -> dict:
    """Collections a catalogue offers, in whichever mode it supports."""
    endpoint = resolve_endpoint(catalog)
    mode = _mode_for(endpoint)
    if mode == "search":
        raw = stac_fetch.list_collections_api(endpoint)
        truncated, used = False, 1
    else:
        walked = stac_fetch.traverse(
            endpoint, collection=None, bbox=None, datetime_spec=None, limit=0,
            fetch=stac_fetch.fetch_json,
        )
        raw, truncated, used = walked["collections"], walked["truncated"], walked["requests_used"]
    return {
        "catalog": endpoint,
        "mode": mode,
        "collections": [flatten_collection(c) for c in raw],
        "truncated": truncated,
        "requests_used": used,
    }


def search_items(
    catalog: str,
    *,
    collection: str | None = None,
    bbox: list[float] | None = None,
    datetime_spec: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Items matching an area and a time range. Never fetches asset bytes."""
    endpoint = resolve_endpoint(catalog)
    mode = _mode_for(endpoint)
    backend = stac_fetch.search_api if mode == "search" else stac_fetch.traverse
    found = backend(
        endpoint, collection=collection, bbox=bbox, datetime_spec=datetime_spec, limit=limit
    )
    items = [flatten_item(i) for i in found["items"]]
    return {
        "catalog": endpoint,
        "mode": mode,
        "bbox": bbox,
        "datetime": datetime_spec,
        "items": items,
        "items_returned": len(items),
        "requests_used": found["requests_used"],
        "truncated": found["truncated"],
    }


def get_item(item_url: str) -> dict:
    """One item, by the 'self' href that catalog-search returns."""
    document = _require_stac(stac_fetch.fetch_json(item_url), item_url)
    return {"item_url": item_url, "item": flatten_item(document)}


def get_assets(item_url: str, *, role: str | None = None, media_type: str | None = None) -> dict:
    """An item's assets: hrefs, advertised metadata, and what can read them."""
    document = _require_stac(stac_fetch.fetch_json(item_url), item_url)
    properties = document.get("properties") or {}
    assets = [
        flatten_asset(key, asset, properties)
        for key, asset in (document.get("assets") or {}).items()
    ]
    if role:
        assets = [a for a in assets if role in a["roles"]]
    if media_type:
        assets = [a for a in assets if a["media_type"] == media_type]
    return {
        "item_url": item_url,
        "item_id": document.get("id"),
        "assets": sorted(assets, key=lambda a: a["key"]),
        "asset_count": len(assets),
    }
```

Extend the `errors` import in `catalog.py` to `from llm_gis.errors import CATALOG_MALFORMED, INPUT_NOT_FOUND, GisError`.

Note the `limit=0` in `list_collections`: the walk records every collection it reaches while collecting no items, which is exactly what a collection listing wants.

- [ ] **Step 5: Run the tests and make sure they pass**

Run: `uv run pytest tests/test_catalog_operations.py -v`
Expected: 11 passed

- [ ] **Step 6: Run the whole offline suite**

Run: `uv run pytest`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add llm_gis/stac_fetch.py llm_gis/catalog.py tests/test_catalog_operations.py
git commit -m "feat(catalog): search backend and the four discovery operations"
```

---

### Task 6: CLI commands, wrappers and documentation

Makes the capability reachable the only way this workspace allows: a `bin/*` command returning JSON.

**Files:**
- Modify: `llm_gis/cli.py`
- Create: `bin/catalog-collections`, `bin/catalog-search`, `bin/catalog-item`, `bin/catalog-assets`
- Modify: `docs/llm/OUTPUT_SCHEMA.md`
- Modify: `README.md`, `AGENTS.md`, `.claude/skills/hot-start/SKILL.md`
- Modify: `tests/test_output_contract.py`

**Interfaces:**
- Consumes: `catalog.list_collections`, `catalog.search_items`, `catalog.get_item`, `catalog.get_assets` (Task 5)
- Produces: four `bin/*` commands whose stdout is a JSON object carrying `status` and `command`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_output_contract.py`:

```python
def test_catalog_search_carries_the_envelope(monkeypatch):
    from llm_gis import catalog

    monkeypatch.setattr(
        catalog, "search_items",
        lambda *a, **k: {"catalog": "x", "mode": "traversal", "items": [], "items_returned": 0,
                         "requests_used": 1, "truncated": False, "bbox": None, "datetime": None},
    )
    payload = _run_ok(CliRunner(), ["catalog-search", "overture"])
    assert payload["status"] == "ok"
    assert payload["command"] == "catalog-search"


def test_catalog_search_rejects_a_malformed_bbox():
    """Four numbers or nothing: exit 2, the caller's typo."""
    result = CliRunner().invoke(app, ["catalog-search", "overture", "--bbox", "1,2,3"])
    assert result.exit_code == 2
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_output_contract.py -v`
Expected: FAIL, both new tests error with "No such command 'catalog-search'"

- [ ] **Step 3: Register the commands**

Add to `llm_gis/cli.py` imports:

```python
from llm_gis import catalog as catalog_ops
```

and add the four commands after `duck_query_cmd`:

```python
def _parse_bbox(bbox: str | None) -> list[float] | None:
    """Four comma-separated numbers, always lon/lat WGS84 for STAC."""
    if bbox is None:
        return None
    parts = [p.strip() for p in bbox.split(",")]
    if len(parts) != 4:
        raise typer.BadParameter("--bbox must be minx,miny,maxx,maxy in lon/lat")
    return [float(p) for p in parts]


@app.command("catalog-collections")
@handle_errors
def catalog_collections_cmd(
    catalog: str = typer.Argument(..., help="Catalogue alias or URL"),
) -> None:
    """Collections a STAC catalogue offers. Never downloads an asset."""
    _emit("catalog-collections", catalog_ops.list_collections(catalog))


@app.command("catalog-search")
@handle_errors
def catalog_search_cmd(
    catalog: str = typer.Argument(..., help="Catalogue alias or URL"),
    collection: str | None = typer.Option(None, "--collection", help="Restrict to one collection id"),
    bbox: str | None = typer.Option(None, "--bbox", help="minx,miny,maxx,maxy in lon/lat WGS84"),
    datetime_spec: str | None = typer.Option(None, "--datetime", help="RFC 3339 instant or start/end range"),
    limit: int = typer.Option(100, "--limit", help="Maximum items to return"),
) -> None:
    """Find items by area and time. Discovery only: no asset bytes are fetched."""
    _emit(
        "catalog-search",
        catalog_ops.search_items(
            catalog,
            collection=collection,
            bbox=_parse_bbox(bbox),
            datetime_spec=datetime_spec,
            limit=limit,
        ),
    )


@app.command("catalog-item")
@handle_errors
def catalog_item_cmd(
    item_url: str = typer.Argument(..., help="Item URL, the 'self' field from catalog-search"),
) -> None:
    """One STAC item, with its properties passed through verbatim."""
    _emit("catalog-item", catalog_ops.get_item(item_url))


@app.command("catalog-assets")
@handle_errors
def catalog_assets_cmd(
    item_url: str = typer.Argument(..., help="Item URL, the 'self' field from catalog-search"),
    role: str | None = typer.Option(None, "--role", help="Keep only assets carrying this role"),
    media_type: str | None = typer.Option(None, "--media-type", help="Keep only this exact media type"),
) -> None:
    """Asset hrefs and advertised metadata. A duckdb-readable href feeds duck-query."""
    _emit("catalog-assets", catalog_ops.get_assets(item_url, role=role, media_type=media_type))
```

- [ ] **Step 4: Create the four wrappers**

```bash
for name in catalog-collections catalog-search catalog-item catalog-assets; do
  cat > "bin/$name" <<EOF
#!/usr/bin/env bash
set -euo pipefail
source "\$(dirname "\$0")/_env.sh"
docker compose --progress quiet run --rm agent uv run --quiet llm-gis $name "\$@"
EOF
  chmod +x "bin/$name"
done
```

- [ ] **Step 5: Document the four commands in OUTPUT_SCHEMA.md**

`tests/test_output_contract.py::test_output_schema_lists_every_bin_command` fails until every new `bin/*` name appears. Add to `docs/llm/OUTPUT_SCHEMA.md` after the `### bin/duck-query` section:

````markdown
### `bin/catalog-collections`

| Key | Type | Meaning |
|---|---|---|
| `catalog` | string | The resolved endpoint URL. |
| `mode` | string | `"search"` or `"traversal"`, how the catalogue was read. |
| `collections` | array | `{id, title, description, license, self, bbox, sub_extents}` per collection. |
| `truncated` | boolean | True when the request budget stopped the walk early. |
| `requests_used` | integer | HTTP requests spent. |

### `bin/catalog-search`

| Key | Type | Meaning |
|---|---|---|
| `catalog` | string | The resolved endpoint URL. |
| `mode` | string | `"search"` (server-side) or `"traversal"` (client-side walk). |
| `bbox` | array or null | The lon/lat WGS84 bbox that was applied. |
| `datetime` | string or null | The range that was applied. |
| `items` | array | `{id, collection, self, bbox, datetime, properties, asset_count}` per item. |
| `items_returned` | integer | Length of `items`. |
| `requests_used` | integer | HTTP requests spent. |
| `truncated` | boolean | True when `--limit` or the request budget cut the result short. A truncated result is not a complete one. |

`--bbox` here is **always lon/lat WGS84**, as the STAC specification requires. `bin/duck-query --bbox` is in the data's own CRS. Same flag name, different meaning.

### `bin/catalog-item`

| Key | Type | Meaning |
|---|---|---|
| `item_url` | string | The URL that was fetched. |
| `item` | object | `{id, collection, self, bbox, datetime, properties, asset_count}`. `properties` is verbatim from the catalogue. |

### `bin/catalog-assets`

| Key | Type | Meaning |
|---|---|---|
| `item_url` | string | The URL that was fetched. |
| `item_id` | string | The item's id. |
| `assets` | array | One entry per asset, see below. |
| `asset_count` | integer | Length of `assets`. |

Each asset: `{key, href, media_type, roles, advertised, readable_by}`.

`advertised` holds the **publisher's claims**, not measurements: `size_bytes` from `file:size`, plus `num_rows`, `eo:cloud_cover` and `proj:epsg` where the collection supplies them. Never read these as QC metrics.

`readable_by` is `["duckdb"]` for Parquet media types and `[]` otherwise. It says what can open the file, not what should: a `[]` asset such as a COG has no reader in this workspace yet.
````

Add the three new codes to the error-code table in the same document:

```markdown
| `CATALOG_UNREACHABLE` | A catalogue could not be reached: DNS, connection, timeout or a 5xx. |
| `CATALOG_MALFORMED` | A catalogue returned a 200 that is not a STAC document. |
| `ITEM_NOT_FOUND` | HTTP 404 for an item URL. |
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `uv run pytest`
Expected: all pass, including `test_output_schema_lists_every_bin_command`

- [ ] **Step 7: Update the three prose docs**

Add to the command table in `.claude/skills/hot-start/SKILL.md`, and mirror in `README.md` and `AGENTS.md`:

```markdown
| `bin/catalog-collections <catalog>` | Collections a STAC catalogue offers |
| `bin/catalog-search <catalog> [--collection] [--bbox] [--datetime] [--limit]` | Find items by area and time |
| `bin/catalog-item <item-url>` | One STAC item |
| `bin/catalog-assets <item-url> [--role] [--media-type]` | Asset hrefs, advertised metadata, and what can read them |
```

Add a "STAC discovery" section to `.claude/skills/hot-start/SKILL.md`:

```markdown
## STAC discovery

Catalogue aliases: `overture` (GeoParquet, static catalogue), `cdse` (Sentinel-2, search
API, anonymous search but downloads need an account), `earth-search` (Sentinel-2, search
API). Any https URL also works.

Discovery never downloads. The chain is: `catalog-search` to find items, take an item's
`self` href, `catalog-assets` on it, then hand a `readable_by: ["duckdb"]` href straight
to `duck-query`. Nothing is staged or ingested.

**`catalog-search --bbox` is lon/lat WGS84. `duck-query --bbox` is in the data's own CRS.**
Same flag name, different meaning, and they are designed to be used back to back.

An asset with `readable_by: []` (a COG, say) has no reader in this workspace until Phase 7.
Values under an asset's `advertised` key are the publisher's claims, not measurements.
```

- [ ] **Step 8: Commit**

```bash
git add llm_gis/cli.py bin/catalog-collections bin/catalog-search bin/catalog-item bin/catalog-assets docs/llm/OUTPUT_SCHEMA.md README.md AGENTS.md .claude/skills/hot-start/SKILL.md tests/test_output_contract.py
git commit -m "feat(catalog): catalog-* commands, wrappers and docs"
```

---

### Task 7: Live tests and the Example 2 chain

Proves the phase's done-when against the real internet, in the suite that is deselected by default.

**Files:**
- Create: `tests/live/test_catalog_remote.py`

**Interfaces:**
- Consumes: everything above, plus `llm_gis.query.query` from Phase 2

- [ ] **Step 1: Write the live tests**

Create `tests/live/test_catalog_remote.py`:

```python
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
```

- [ ] **Step 2: Confirm they are deselected by default**

Run: `uv run pytest`
Expected: the four new tests are not collected

- [ ] **Step 3: Run them against the real internet**

Run: `uv run pytest -m live tests/live/test_catalog_remote.py -v`
Expected: 4 passed

If `test_example_2_discovery_feeds_duckdb_with_no_ingestion` returns zero rows, the Oslo bbox missed the part-file the traversal picked. Widen `OSLO`, or drop `limit=1` on the search so more than one part-file is considered. Do not weaken the `matched_row_count > 0` assertion: a chain that returns nothing has not demonstrated the done-when.

- [ ] **Step 4: Run the full suite both ways**

Run: `uv run pytest && uv run pytest -m live tests/live/test_catalog_remote.py`
Expected: both green

- [ ] **Step 5: Commit**

```bash
git add tests/live/test_catalog_remote.py
git commit -m "test(catalog): live STAC smoke tests and the Example 2 chain"
```

---

### Task 8: Field test

The plan's standing rule: a phase is not done until a real job has run through the `bin/*` commands. Passing tests prove the code runs; only a field test shows whether the workflow holds.

**Files:**
- Create: `docs/reports/2026-09-07_phase4-stac-field-test.md`

- [ ] **Step 1: Bring the stack up and confirm the commands exist**

```bash
docker compose up -d --build
bin/doctor
bin/catalog-collections overture
```

- [ ] **Step 2: Run the Example 2 chain through the wrappers, not the library**

```bash
bin/catalog-search overture --collection building --bbox 10.6,59.8,10.9,60.0 --limit 1
bin/catalog-assets <self-href-from-above> --role data
bin/duck-query <parquet-href> --bbox 10.6,59.8,10.9,60.0 --limit 100 \
  --output /data/outgoing/2026-09-07_stac-discovery/buildings.parquet
bin/qc /data/outgoing/2026-09-07_stac-discovery/buildings.parquet --expect-non-empty
```

- [ ] **Step 3: Exercise the CRS footgun deliberately**

Run a `catalog-search --bbox` and a `duck-query --bbox` against an asset in a projected CRS, passing the same four numbers to both. Record what happens. The spec predicts this bites; the field test is where we find out how hard.

- [ ] **Step 4: Time the traversal**

Record wall-clock time and `requests_used` for the `catalog-search` above. The spec defers a document cache under `/data/work/cache/stac/` and names it the first thing to build if traversal proves slow. This step is the evidence for that decision.

- [ ] **Step 5: Write the report**

Create `docs/reports/2026-09-07_phase4-stac-field-test.md` covering: what ran, the commands verbatim, the numbers observed, whether the CRS footgun bit and how, traversal timing against the deferred cache decision, and anything the test suite could not have caught. Follow the shape of `docs/reports/2026-09-07_phase3-qc-field-test.md`.

- [ ] **Step 6: Commit**

```bash
git add docs/reports/2026-09-07_phase4-stac-field-test.md
git commit -m "docs: Phase 4 STAC discovery field test"
```
