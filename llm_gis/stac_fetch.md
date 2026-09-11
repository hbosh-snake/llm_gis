# stac_fetch.py

## What it does

Every network call the STAC discovery feature makes, and nothing else — kept
apart from `catalog.py` on purpose, so every output shape in `catalog.py` can
be tested against a recorded fixture with no network involved, and so the
request budget has exactly one choke point.

## When you'd call it

Never directly from the CLI — it's the network layer underneath
`bin/catalog-collections`, `bin/catalog-search`, `bin/catalog-item`,
`bin/catalog-assets`. You'd read or modify this module when changing how
catalogue traversal, search, or HTTP error handling behaves.

## Key functions and classes

- `fetch_json(url)` — one GET returning a STAC document. No retries — a
  flaky catalogue says so via a raised `GisError`, rather than silently
  masking the problem. Distinguishes `404` (`ITEM_NOT_FOUND`), other `4xx`/
  `5xx` (`CATALOG_UNREACHABLE`), a non-JSON `200` and non-dict JSON (both
  `CATALOG_MALFORMED`).
- `detect_mode(root)` — `"search"` if the catalogue's root document declares
  the `/item-search` STAC conformance class, else `"traversal"`.
- `Budget(max_requests)` — a request allowance that truncates rather than
  raises once spent; every traversal respects `MAX_REQUESTS` (200) and
  `MAX_DEPTH` (5).
- `traverse(root_url, collection, bbox, datetime_spec, limit, fetch=None, latest_only=False)`
  — walks a static catalogue's JSON tree client-side, filtering by a
  collection's advertised sub-extents before descending (`_prefilter_allows`)
  and matching bbox/datetime per item once fetched. `latest_only` follows
  only STAC `{"latest": true}`-marked child links (Overture's release
  catalogue marks exactly one per document), cutting request count roughly
  in proportion to release count.
- `search_api(endpoint, collection, bbox, datetime_spec, limit)` — delegates
  to `pystac_client.Client.search` for catalogues with a real search API;
  `pystac-client` objects stay inside this one function.
- `list_collections_api(endpoint)` — collection documents via
  `Client.get_collections()`.
- `bbox_intersects`, `matches_datetime` — pure filter predicates used during
  traversal; a missing bbox filters nothing, a missing datetime never
  matches a declared spec (excluded rather than silently passed through).

## A documented STAC quirk this module handles

`_sub_extents`/`_child_links` account for Overture's static catalogue not
following STAC's documented bbox-array convention (an overall extent at index
0, then one sub-extent per item) — Overture instead lists exactly one bbox per
item with no leading overall entry. The item count settles which convention a
given document actually uses, rather than assuming the spec's convention
blindly and silently misaligning sub-extents with the wrong items.

## How it fits the overall flow

Sits under `catalog.py`, which owns the STAC discovery entry points and never
makes an HTTP call itself — every network hop is here.
