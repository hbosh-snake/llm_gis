# catalog.py

## What it does

STAC (SpatioTemporal Asset Catalog) discovery: what data exists out there, and
what could read it, without ever downloading an asset's bytes. Everything
returned is either the publisher's own metadata (quarantined as `advertised`
where relevant) or a classification computed from an href's text
(`planner.classify`) — never a measurement of the asset itself.

## When you'd call it

Via `bin/catalog-collections`, `bin/catalog-search`, `bin/catalog-item`,
`bin/catalog-assets` — the first step of any workflow that starts from a
catalogue (Overture, Copernicus/CDSE, Earth Search, or any STAC-compliant
https URL) rather than a file already in `data/incoming/`.

## Key functions

- `resolve_endpoint(catalog)` — expands an alias (`overture`, `cdse`,
  `earth-search`) or passes a full URL through.
- `list_collections(catalog, latest_only=False)` — collections a catalogue
  offers, in whichever mode it supports (see below).
- `search_items(catalog, collection, bbox, datetime_spec, limit)` — items
  matching an area/time. **`bbox` here is always lon/lat WGS84** — the STAC
  spec's own coordinate system — regardless of a matched asset's native CRS.
  This differs from `query.query`'s `bbox`, which is in the source's own CRS;
  the two are meant to be chained (search in WGS84, reproject, then filter).
- `get_item(item_url)` — one item by its `self` href.
- `get_assets(item_url, role=None, media_type=None)` — an item's assets: hrefs,
  advertised metadata, and `readers`/`readable_by` (what can open them).
- `readable_by(media_type)` / `readers_for(href)` — compatibility surfaces.
  `readers_for` delegates to `planner.classify`, the single authoritative
  format-to-engine table; `readable_by` is a narrower, Parquet-only projection
  of it, kept for backward compatibility with `duck-query`.

## Two catalogue modes

A catalogue either declares the STAC `/item-search` conformance class (a
server-side search API, e.g. Earth Search/CDSE) or it doesn't, in which case
`stac_fetch.traverse` walks its static JSON tree client-side under a request
budget. `catalog.py` detects which mode applies (`stac_fetch.detect_mode`) and
routes to `stac_fetch.search_api` or `stac_fetch.traverse` accordingly — the
caller never needs to know which.

## How it fits the overall flow

`catalog.py` is the entry point for STAC discovery; `stac_fetch.py` is the
network layer underneath it (kept separate so every output shape can be tested
from a recorded fixture, no network needed). Discovery never stages or
ingests: the chain is `catalog-search` → take an item's `self` href →
`catalog-assets` on it → hand a Parquet href straight to `bin/duck-query`, or a
COG href straight to `bin/raster-window`/`bin/inspect`.
