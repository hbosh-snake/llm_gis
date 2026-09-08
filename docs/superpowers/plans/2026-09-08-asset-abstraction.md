# Asset Abstraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `inspect`, `duck-describe` and `catalog-assets` one internal descriptor type, `llm_gis/asset.py`, without changing a single byte of their JSON output.

**Architecture:** A stdlib dataclass `Asset` holds the facts the three producers already emit, using one canonical name per concept. Each producer builds an `Asset` and then hands it to a private serializer, living in that producer's own module, which maps the canonical names back to the historic JSON keys its callers know. `asset.py` itself knows nothing about any command's output shape.

**Tech Stack:** Python 3.12, stdlib `dataclasses` (no new dependency — Pydantic is named in the hot-start doc but is not in `pyproject.toml` and is imported nowhere), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-09-07-asset-abstraction-design.md`

## Global Constraints

- **No output changes.** Every command's JSON stays key-for-key identical. `docs/llm/OUTPUT_SCHEMA.md` must not be edited; an unchanged diff on that file is part of the acceptance evidence.
- **Existing tests pass unchanged.** No edits to `tests/test_output_contract.py`, `tests/test_inspect.py`, `tests/test_duck.py`, `tests/test_catalog_operations.py`, `tests/test_stac_shape.py`, or any fixture. Needing to loosen an existing assertion means the extraction is wrong, not the test.
- **Top-level fields carry measurements only.** A publisher's claims stay under `advertised` and are never promoted to `crs`, `bbox` or `record_count`.
- **No new I/O.** No hashing, no network calls, no extra file reads. `content_hash` stays `None` in this phase.
- **Provenance fields are always present**, defaulting to `None`. The block never changes shape by source type.
- **`record_count` stays `None` for `inspect`.** It has no top-level count, only per-layer `feature_count`. Do not sum layers.
- Run everything with `uv run`, never bare `python3`/`pytest`.
- Public signatures already used elsewhere must not break: `flatten_asset(key, asset, properties)` is called positionally in `tests/test_stac_shape.py`; `describe(uri)` is imported by `llm_gis/exporter.py` and `llm_gis/cli.py`; `inspect_dataset` is imported by `llm_gis/ingest_vector.py` and `llm_gis/ingest_raster.py`.
- Docstring comments over inline comments. No emojis in code.

## File Structure

| File | Responsibility |
|---|---|
| `llm_gis/asset.py` (create) | The `Asset`, `Provenance`, `Column`, `Layer`, `Band` dataclasses and the three `source_type` constants. Pure data; imports nothing from the producer modules. |
| `llm_gis/catalog.py` (modify) | Gains `build_asset()`; `flatten_asset()` becomes `build_asset()` + `_to_asset_json()`. |
| `llm_gis/duck.py` (modify) | `describe()` builds an `Asset`, then `_to_describe()` serializes it. |
| `llm_gis/inspect.py` (modify) | `inspect_dataset()` builds an `Asset` per branch, then `_to_report()` serializes it. |
| `tests/test_asset.py` (create) | Construction defaults per source type, plus one round-trip assertion per producer. |
| `.claude/skills/hot-start/SKILL.md` (modify) | Records the new module, per the CLAUDE.md rule for new modules. |

---

### Task 1: The model

**Files:**
- Create: `llm_gis/asset.py`
- Test: `tests/test_asset.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Asset`, `Provenance`, `Column`, `Layer`, `Band`, and the constants `LOCAL_FILE = "local_file"`, `REMOTE_URI = "remote_uri"`, `STAC_ASSET = "stac_asset"`. `Asset` takes exactly two positional fields, `uri` then `provenance`; everything else is keyword with a default. `Provenance` takes `source_type` positionally; every other field is keyword and defaults to `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_asset.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_asset.py -v`
Expected: FAIL, collection error — `ModuleNotFoundError: No module named 'llm_gis.asset'`.

- [ ] **Step 3: Write the model**

Create `llm_gis/asset.py`:

```python
"""One descriptor for anything this workspace can point at.

Three producers describe datasets -- inspect, duck-describe and catalog-assets --
and each grew its own vocabulary for the same facts. This module holds the shape
they have in common, extracted from what they emit rather than imagined ahead of
them: every field here is populated by at least one of the three today.

Top-level fields carry measurements only, meaning something opened the source and
read what was there. A publisher's claims stay under `advertised` and are never
promoted, so a STAC asset nobody has opened reports None for the facts nobody has
checked. That is the model stating its ignorance, not a gap to be filled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOCAL_FILE = "local_file"
REMOTE_URI = "remote_uri"
STAC_ASSET = "stac_asset"


@dataclass
class Column:
    """One column of a tabular source, named as the reading engine spells it."""

    name: str
    type: str


@dataclass
class Layer:
    """One vector layer."""

    name: str | None
    geometry_type: str | None
    feature_count: int | None


@dataclass
class Band:
    """One raster band."""

    band: int | None
    type: str | None
    nodata: float | None


@dataclass
class Provenance:
    """Where an asset came from.

    Every field is present always and None where it does not apply, so the block
    never changes shape by source type. `content_hash` is filled only by producers
    that already hash their input; describing a dataset does not hash it.
    """

    source_type: str
    retrieved_at: str | None = None
    catalog_url: str | None = None
    item_id: str | None = None
    asset_key: str | None = None
    content_hash: str | None = None


@dataclass
class Asset:
    """A dataset we can point at: where it is, what it holds, where it came from."""

    uri: str | None
    provenance: Provenance
    dataset_kind: str | None = None
    media_type: str | None = None
    roles: list[str] = field(default_factory=list)
    readable_by: list[str] = field(default_factory=list)
    crs: str | None = None
    crs_status: str | None = None
    crs_reasons: list[str] = field(default_factory=list)
    bbox: dict[str, float] | None = None
    record_count: int | None = None
    geometry_column: str | None = None
    columns: list[Column] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    size: list[int] | None = None
    advertised: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_asset.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add llm_gis/asset.py tests/test_asset.py
git commit -m "feat: add the shared Asset descriptor"
```

---

### Task 2: Wire catalog-assets

The smallest producer, and the one whose provenance is richest. `get_assets` currently discards `item_url` and the document id when flattening each asset; both become provenance.

**Files:**
- Modify: `llm_gis/catalog.py:70-83` (`flatten_asset`) and `llm_gis/catalog.py:202-219` (`get_assets`)
- Test: `tests/test_asset.py`

**Interfaces:**
- Consumes: `Asset`, `Provenance`, `STAC_ASSET` from Task 1.
- Produces: `build_asset(key, asset, properties, *, item_url=None, item_id=None) -> Asset` and `_to_asset_json(asset) -> dict`. `flatten_asset` keeps its three positional parameters — `tests/test_stac_shape.py` calls it positionally — and gains the same two keyword-only extras.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_asset.py`:

```python
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
```

The fixture is the one `tests/test_stac_shape.py` already loads: `tests/fixtures/stac/overture_item.json`. Do not add a new fixture.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_asset.py -v`
Expected: FAIL with `AttributeError: module 'llm_gis.catalog' has no attribute 'build_asset'`.

- [ ] **Step 3: Rewrite `flatten_asset` as build + serialize**

In `llm_gis/catalog.py`, add to the imports at the top:

```python
from llm_gis.asset import STAC_ASSET, Asset, Provenance
```

Replace the whole of `flatten_asset` (currently lines 70-83) with:

```python
def build_asset(
    key: str,
    asset: dict,
    properties: dict,
    *,
    item_url: str | None = None,
    item_id: str | None = None,
) -> Asset:
    """One STAC asset as an Asset, with the publisher's claims left under `advertised`.

    Nothing here is measured: no asset bytes are fetched, so `crs`, `bbox` and
    `record_count` stay None however much the publisher advertises.
    """
    advertised = {"size_bytes": asset.get("file:size")}
    for name in ADVERTISED_PROPERTIES:
        if name in properties:
            advertised[name] = properties[name]
    return Asset(
        uri=asset.get("href"),
        provenance=Provenance(
            STAC_ASSET, catalog_url=item_url, item_id=item_id, asset_key=key
        ),
        media_type=asset.get("type"),
        roles=asset.get("roles") or [],
        readable_by=readable_by(asset.get("type")),
        advertised=advertised,
    )


def _to_asset_json(asset: Asset) -> dict:
    """The historic per-asset keys, unchanged."""
    return {
        "key": asset.provenance.asset_key,
        "href": asset.uri,
        "media_type": asset.media_type,
        "roles": asset.roles,
        "advertised": asset.advertised,
        "readable_by": asset.readable_by,
    }


def flatten_asset(
    key: str,
    asset: dict,
    properties: dict,
    *,
    item_url: str | None = None,
    item_id: str | None = None,
) -> dict:
    """One asset, with the publisher's claims quarantined under 'advertised'."""
    return _to_asset_json(
        build_asset(key, asset, properties, item_url=item_url, item_id=item_id)
    )
```

- [ ] **Step 4: Pass the item's identity through `get_assets`**

In `llm_gis/catalog.py:206-209`, replace the assets comprehension so provenance is populated:

```python
    assets = [
        flatten_asset(key, asset, properties, item_url=item_url, item_id=document.get("id"))
        for key, asset in (document.get("assets") or {}).items()
    ]
```

Everything else in `get_assets` stays as it is: `item_url`, `item_id` and `asset_count` remain item-level keys.

- [ ] **Step 5: Run the new tests and the whole catalog suite**

Run: `uv run pytest tests/test_asset.py tests/test_stac_shape.py tests/test_catalog_operations.py tests/test_catalog_errors.py tests/test_catalog_aliases.py tests/test_catalog_budget.py -v`
Expected: PASS, everything green, with no edit to any file under `tests/` other than `tests/test_asset.py`.

- [ ] **Step 6: Commit**

```bash
git add llm_gis/catalog.py tests/test_asset.py
git commit -m "refactor: catalog-assets builds an Asset"
```

---

### Task 3: Wire duck-describe

**Files:**
- Modify: `llm_gis/duck.py:39-72` (`describe`)
- Test: `tests/test_asset.py`

**Interfaces:**
- Consumes: `Asset`, `Provenance`, `Column`, `LOCAL_FILE`, `REMOTE_URI` from Task 1.
- Produces: `_build_asset(uri, columns, row_count, geometry, bbox, crs) -> Asset` and `_to_describe(asset) -> dict`, both private to `duck.py`. `describe(uri)` keeps its signature and its exact return keys — `llm_gis/exporter.py` and `llm_gis/cli.py` both consume it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_asset.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_asset.py -v`
Expected: FAIL with `AttributeError: module 'llm_gis.duck' has no attribute '_build_asset'`.

- [ ] **Step 3: Build an Asset inside `describe`**

In `llm_gis/duck.py`, add to the imports:

```python
from llm_gis.asset import LOCAL_FILE, REMOTE_URI, Asset, Column, Provenance
```

Replace the `columns` comprehension inside `describe` (currently `llm_gis/duck.py:43-48`) so it yields `Column` records:

```python
        columns = [
            Column(name, type_)
            for name, type_ in connection.execute(
                "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))", [uri]
            ).fetchall()
        ]
```

Then update the two lines that read a column's type (`llm_gis/duck.py:59-61`) and the return, so the tail of `describe` becomes:

```python
    meta = _geo_metadata(connection, uri)
    geometry = next((c for c in columns if c.type.upper().startswith("GEOMETRY")), None)
    bbox = _bbox(connection, uri, geometry.name) if geometry else None
    crs = _crs_from_type(geometry.type) if geometry else None
    if crs is None and meta:
        crs = _crs_from_geo_metadata(meta)

    return _to_describe(
        _build_asset(uri, columns, row_count, geometry.name if geometry else None, bbox, crs)
    )
```

Add both helpers immediately after `describe`:

```python
def _build_asset(
    uri: str,
    columns: list[Column],
    row_count: int,
    geometry_column: str | None,
    bbox: dict[str, float] | None,
    crs: str | None,
) -> Asset:
    """What DuckDB measured, as an Asset. Everything here was read, not advertised."""
    source_type = REMOTE_URI if uri.startswith(("http://", "https://", "s3://")) else LOCAL_FILE
    return Asset(
        uri=uri,
        provenance=Provenance(source_type),
        crs=crs,
        bbox=bbox,
        record_count=row_count,
        geometry_column=geometry_column,
        columns=columns,
    )


def _to_describe(asset: Asset) -> dict[str, Any]:
    """The historic duck-describe keys, unchanged."""
    return {
        "uri": asset.uri,
        "row_count": asset.record_count,
        "columns": [{"name": c.name, "type": c.type} for c in asset.columns],
        "geometry_column": asset.geometry_column,
        "crs": asset.crs,
        "bbox": asset.bbox,
    }
```

- [ ] **Step 4: Run the DuckDB suite**

Run: `uv run pytest tests/test_asset.py tests/test_duck.py tests/test_qc_file.py tests/test_qc_export.py -v`
Expected: PASS. `test_qc_file.py` and `test_qc_export.py` are included because `llm_gis/exporter.py` imports `describe`; if either fails, the return keys drifted.

- [ ] **Step 5: Commit**

```bash
git add llm_gis/duck.py tests/test_asset.py
git commit -m "refactor: duck-describe builds an Asset"
```

---

### Task 4: Wire inspect

The largest producer, done last: two branches, and the only one whose historic key names all differ from the canonical ones.

**Files:**
- Modify: `llm_gis/inspect.py:60-160` (`inspect_dataset`)
- Test: `tests/test_asset.py`

**Interfaces:**
- Consumes: `Asset`, `Provenance`, `Band`, `Layer`, `LOCAL_FILE` from Task 1.
- Produces: `_build_vector_asset(input_path, vector_out) -> Asset`, `_build_raster_asset(input_path, raster_out) -> Asset` and `_to_report(asset) -> dict`, all private to `inspect.py`. `inspect_dataset(input_path, ingest_id=None)` keeps its signature and its exact return keys — `ingest_vector.py` and `ingest_raster.py` both read `detected_crs` and `crs_status` from it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_asset.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_asset.py -v`
Expected: FAIL with `ImportError: cannot import name '_build_vector_asset' from 'llm_gis.inspect'`.

- [ ] **Step 3: Build an Asset in each branch**

In `llm_gis/inspect.py`, add to the imports:

```python
from llm_gis.asset import LOCAL_FILE, Asset, Band, Layer, Provenance
```

Add these three functions above `inspect_dataset`:

```python
def _build_vector_asset(input_path: Path, payload: dict[str, Any]) -> Asset:
    """What ogrinfo measured, as an Asset.

    `record_count` stays None: there is only a count per layer here, and summing
    them would publish a number no caller has ever been given.
    """
    extent = _extract_vector_extent(payload)
    first_layer = (payload.get("layers") or [{}])[0]
    field = (first_layer.get("geometryFields") or [{}])[0]
    crs_text = normalize_crs(crs_text_from_ogr_coordinate_system(field.get("coordinateSystem") or {}))
    status, reasons = crs_status(crs_text, extent)
    return Asset(
        uri=str(input_path),
        provenance=Provenance(LOCAL_FILE, retrieved_at=utc_now()),
        dataset_kind="vector",
        crs=crs_text,
        crs_status=status,
        crs_reasons=reasons,
        bbox=extent,
        layers=[
            Layer(
                layer.get("name"),
                ((layer.get("geometryFields") or [{}])[0] or {}).get("type"),
                layer.get("featureCount"),
            )
            for layer in payload.get("layers", [])
        ],
        raw=payload,
    )


def _build_raster_asset(input_path: Path, payload: dict[str, Any]) -> Asset:
    """What gdalinfo measured, as an Asset."""
    extent = _extract_raster_extent(payload)
    crs_text = normalize_crs(payload.get("coordinateSystem", {}).get("wkt"))
    status, reasons = crs_status(crs_text, extent)
    return Asset(
        uri=str(input_path),
        provenance=Provenance(LOCAL_FILE, retrieved_at=utc_now()),
        dataset_kind="raster",
        crs=crs_text,
        crs_status=status,
        crs_reasons=reasons,
        bbox=extent,
        size=payload.get("size"),
        bands=[
            Band(band.get("band"), band.get("type"), band.get("noDataValue"))
            for band in payload.get("bands", [])
        ],
        raw=payload,
    )


def _to_report(asset: Asset) -> dict[str, Any]:
    """The historic inspect keys, unchanged.

    Canonical names map back here: uri to input_path, bbox to extent, crs to
    detected_crs, retrieved_at to created_at. The vector and raster branches
    differ only in whether layers or size-and-bands appear.
    """
    report: dict[str, Any] = {
        "dataset_kind": asset.dataset_kind,
        "input_path": asset.uri,
    }
    if asset.dataset_kind == "vector":
        report["layers"] = [
            {"name": l.name, "geometry_type": l.geometry_type, "feature_count": l.feature_count}
            for l in asset.layers
        ]
    else:
        report["size"] = asset.size
        report["bands"] = [
            {"band": b.band, "type": b.type, "nodata": b.nodata} for b in asset.bands
        ]
    report["detected_crs"] = asset.crs
    report["extent"] = asset.bbox
    report["crs_status"] = asset.crs_status
    report["crs_reasons"] = asset.crs_reasons
    report["raw"] = asset.raw
    report["created_at"] = asset.provenance.retrieved_at
    return report
```

- [ ] **Step 4: Replace the two inline report bodies**

In `inspect_dataset`, delete both `report = {...}` literals and the `if vector_out: ... else: ...` bodies that build them, keeping the two `ogrinfo`/`gdalinfo` calls and the `UNSUPPORTED_FORMAT` guard exactly as they are. The tail of the function becomes:

```python
    if vector_out:
        asset = _build_vector_asset(input_path, vector_out)
    else:
        asset = _build_raster_asset(input_path, raster_out or {})
    report = _to_report(asset)

    if ingest_id:
        write_json(work_root() / "reports" / f"{ingest_id}.json", report)
    return report
```

- [ ] **Step 5: Run the inspect and ingest suites**

Run: `uv run pytest tests/test_asset.py tests/test_inspect.py tests/test_errors.py tests/test_ingest_vector.py tests/test_crs_status.py -v`
Expected: PASS. `test_ingest_vector.py` matters because `ingest_vector.py` reads `detected_crs` and `crs_status` off this report.

- [ ] **Step 6: Commit**

```bash
git add llm_gis/inspect.py tests/test_asset.py
git commit -m "refactor: inspect builds an Asset"
```

---

### Task 5: Record the module and prove the contract held

**Files:**
- Modify: `.claude/skills/hot-start/SKILL.md`
- Verify: `docs/llm/OUTPUT_SCHEMA.md` is untouched

**Interfaces:**
- Consumes: everything from Tasks 1-4.
- Produces: nothing consumed by later tasks; this is the acceptance gate.

- [ ] **Step 1: Run the whole suite**

Run: `uv run pytest -v`
Expected: PASS, all green. Any failure here is a real regression, not a test to adjust.

- [ ] **Step 2: Prove no test or fixture was edited**

Run: `git diff --stat main -- tests/ docs/llm/OUTPUT_SCHEMA.md`
Expected: exactly one line, `tests/test_asset.py`, with only additions. `docs/llm/OUTPUT_SCHEMA.md` must not appear at all. If any other test file appears in that diff, stop and revert the edit to it — a changed test invalidates the acceptance evidence.

- [ ] **Step 3: Record the new module**

In `.claude/skills/hot-start/SKILL.md`, add this paragraph immediately after the "Architecture (3 layers)" section:

```markdown
## The asset descriptor

`llm_gis/asset.py` holds `Asset`, the one shape `inspect`, `duck-describe` and
`catalog-assets` all build internally. Top-level fields carry measurements only;
a publisher's claims stay under `advertised` and are never promoted. Provenance
travels with the asset: source type, retrieval time, catalogue and item id where
applicable, and a `content_hash` slot that only producers which already hash
their input fill. Each command serializes the asset back to its own historic JSON
keys, so the descriptor is internal and no output changed when it landed.
```

- [ ] **Step 4: Verify the docs claim is true**

Run: `uv run llm-gis inspect tests/fixtures/aoi.gpkg | head -5` (or `bin/inspect` if the Docker stack is up)
Expected: the same JSON keys the command emitted before this plan — `dataset_kind`, `input_path`, `layers`, and so on.

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/hot-start/SKILL.md
git commit -m "docs: record the asset descriptor in hot-start"
```
