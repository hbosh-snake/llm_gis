# Phase 4 — STAC discovery: design

**Status:** approved design, not yet implemented.
**Plan reference:** `docs/plans/2026-09-04_improvement_plan_revised.md`, "Phase 4 — STAC discovery (O2)".
**Date:** 2026-09-07.

## Purpose

Let the operator find remote datasets without downloading them. A caller names a
catalogue, an area and a time range; the answer is a list of items and, for a chosen item,
a list of asset hrefs with enough advertised metadata to decide whether an asset is worth
opening. Phase 2's `duck-query` then reads a GeoParquet href directly. Nothing is staged,
nothing is ingested, no asset bytes are fetched.

## The finding that shapes this phase

The plan's Phase 4 headline command is item search, and its done-when is Example 2:
public STAC, discover a remote GeoParquet asset, DuckDB bbox query, no ingestion. Probing
the candidate endpoints on 2026-09-07 showed those two point at different catalogues.

| Endpoint | Item Search | Assets | Anonymous asset read |
|---|---|---|---|
| `https://stac.overturemaps.org/` | no, static catalogue | GeoParquet, public S3 and Azure | yes |
| `https://stac.dataspace.copernicus.eu/v1/` | yes, anonymous | Sentinel-2 COG and SAFE | no, HTTP 401 |
| `https://earth-search.aws.element84.com/v1/` | yes, anonymous | Sentinel-2 COG | yes, but unreadable until Phase 7 |

No public catalogue serves GeoParquet assets *and* a search endpoint. The only catalogue
that closes the Example 2 loop is static, and every catalogue with a real `/search` serves
rasters this repository cannot read until Phase 7.

Phase 4 therefore implements **two discovery modes**, not one. Dropping traversal makes the
phase's done-when unreachable; dropping search leaves the module unable to touch Sentinel-2,
which is what every job in `docs/reports/` is actually about.

This also settles the plan's open question 2. The live smoke tests target both: **Overture**
for the Example 2 chain, **CDSE** for the search API. CDSE's search is anonymous even
though its downloads are not, which suits a layer that never downloads.

## Scope

In scope:

- Collection listing, item search in both modes, item fetch, asset listing.
- Four commands: `catalog-collections`, `catalog-search`, `catalog-item`, `catalog-assets`.
- Anonymous, public catalogues.

Deferred, deliberately:

- **`catalog-add` and `/data/work/catalogs.json`.** See "Registration is deferred" below.
- **Caching.** See "Caching is deferred" below.
- **Remote QC.** See "Advertised metadata replaces remote QC" below.
- Authenticated catalogues and credential passing. No current endpoint needs them for
  discovery; CDSE needs them only for download, which this phase does not do.
- Raster asset consumption. `catalog-assets` reports a COG href; reading it is Phase 7.

## Registration is deferred

The plan specifies registered endpoints persisted in `/data/work/catalogs.json`. This phase
ships instead a plain dict in `catalog.py` mapping `overture`, `cdse` and `earth-search` to
their URLs, with `--catalog` accepting either an alias or any URL.

Registration exists to turn a long URL into a short name, and there are three endpoints
worth naming, all known at design time. It would also be the phase's only new mutable
state, living on a scratch mount, so a registry that vanishes when `work/` is cleaned is a
registry no caller can rely on. This is the plan's own D4 reasoning, one phase later: a
registry describing three endpoints is a lookup table wearing architecture's clothes.

Nothing gets harder by waiting. If a fourth catalogue or a private endpoint ever needs
persisting, `catalogs.json` layers on top of alias resolution without changing the command
interface.

## Caching is deferred

An earlier draft cached conformance detection under `/data/work/cache/stac/`. It is not
worth building.

Conformance comes from the catalogue root document, which traversal must fetch anyway.
Caching it saves roughly one request per invocation and costs a cache file, a TTL, an
invalidation story, and a staleness failure mode in which a catalogue gains Item Search and
this code keeps walking it until the entry expires.

The cache worth having is different: caching the fetched STAC documents themselves would
make a repeated walk over the same static catalogue cheap. But the request budget already
bounds the cost of a single walk, and no walk has yet been run twice. **If the field test
finds traversal slow, a document cache under `/data/work/cache/stac/` is the first thing to
build.** That is the deferral, recorded so the next phase does not have to rediscover it.

## Advertised metadata replaces remote QC

Phase 3 deferred remote URIs as a QC source over unbounded network cost. Phase 4 does not
change that arithmetic. A QC pass is a full scan, and an Overture buildings part-file is
hundreds of megabytes. `duck-describe` on a remote GeoParquet is costly for the same
reason: its bbox comes from `min(ST_XMin(geom))`, a full column read, not from the footer.

A STAC item already advertises, for free and without reading a byte of asset data, most of
what a pre-flight check wants. The Overture item probed on 2026-09-07 carries `bbox` and
`num_rows`; a Sentinel-2 item carries `bbox`, `datetime`, `eo:cloud_cover` and `proj:epsg`.

So `catalog-assets` is the zero-cost pre-flight. A caller can decide "this asset is 400 MB
and its bbox does not touch my AOI" before opening a connection. QC keeps its current
contract and runs, as it does today, over the local result `duck-query` writes. This needs
no new QC code and is strictly cheaper than the alternative.

`bin/qc` does not accept a remote href in this phase.

## Architecture

```
bin/catalog-search <catalog> [--collection] [--bbox] [--datetime] [--limit]
                      |
              llm_gis/catalog.py     aliases, four operations, flatteners (pure)
                      |
              llm_gis/stac_fetch.py  all network I/O
                      |
        open_catalog(url) -> conformsTo -> mode
                      |
         +------------+------------+
         |                         |
   search backend            traversal backend
   pystac-client             child-link walk, extent prefilter,
   /search, one request      client-side bbox and datetime, budgeted
```

Two modules, split on the same seam Phase 3 used between `qc.py` and `qc_collect.py`: pure
functions on one side, I/O on the other.

- **`llm_gis/catalog.py`** — alias resolution, the four public operations, and the
  flatteners that turn a STAC object into a plain dict.
- **`llm_gis/stac_fetch.py`** — opening a client, conformance detection, the two backends,
  the request budget.

The payoff is the one Phase 3 got: every field of every output shape is exercisable from a
recorded JSON fixture with no network. The plan asks for recorded fixtures covering search,
item and asset parsing; this seam is what makes that achievable rather than aspirational.

pystac-client objects never leave `stac_fetch.py`. `catalog.py` sees dicts and callers see
dicts, matching `duck.describe`.

## Commands

```
bin/catalog-collections <catalog>
bin/catalog-search      <catalog> [--collection C] [--bbox W,S,E,N]
                                  [--datetime RANGE] [--limit N]
bin/catalog-item        <item-url>
bin/catalog-assets      <item-url> [--role data] [--media-type ...]
```

`<catalog>` is an alias or a URL. Each is a three-line `bin/*` wrapper in the existing idiom.

`catalog-item` and `catalog-assets` take a **single item URL**, not catalogue plus
collection plus id. Every item in `catalog-search` output carries its `self` href, so the
URL is always to hand. Both commands are then one plain HTTP GET behaving identically in
both modes: no conformance detection, no traversal, and no id-resolution logic that would
need one implementation for an API and another for a static catalogue, where reaching item
`00000` of collection `building` means walking `buildings/building/00000/00000.json`.

`catalog-item` returns the whole item. `catalog-assets` returns only the asset table and is
where the "can Phase 2 read this?" judgement lives. Its `--role` and `--media-type` flags
filter that table by exact match; both default to unset, which returns every asset.

`catalog-collections` is mode-aware like `catalog-search`. Against a search API it reads
`/collections`. Against a static catalogue it walks `child` links under the same depth cap
and request budget as traversal, and reports `truncated` on the same terms.

## Mode detection and the two backends

`open_catalog(url)` fetches the root document once and reads `conformsTo`. A catalogue
declaring Item Search gets `mode: "search"`; anything else gets `mode: "traversal"`. Every
`catalog-search` result carries `mode`, so a caller always knows which it got.

**Search backend.** `--collection`, `--bbox` and `--datetime` pass to pystac-client's
`search()`. Server-side filtering, one request.

**Traversal backend**, in cost order:

1. Walk `child` links to reach collections, to a depth of 5, with a visited-set of resolved
   hrefs for cycle protection. Without `--collection`, every collection reached is searched;
   with it, only the matching one, and unmatched branches are never descended.
2. **Bbox prefilter from the collection's `extent.spatial.bbox` array**, before fetching any
   item JSON. STAC puts per-item sub-extents in elements 1..n of that array. On Overture
   buildings this turns 512 item fetches into one 158 KB fetch. This is standard STAC, not
   an Overture special case, and it degrades gracefully: a collection publishing only an
   overall bbox skips the prefilter and pays full price under the budget.
3. Fetch the surviving item JSONs, apply bbox and datetime exactly, and stop at `--limit`
   or the request budget. An item carrying no `datetime` is excluded whenever `--datetime`
   is given, rather than being passed through unfiltered.

**Budgets.** `--limit` defaults to 100, matching pystac-client's own default. A separate
hard budget of 200 HTTP fetches bounds the walk, because a bbox matching nothing can burn
requests without returning items. Every result carries `truncated`, `items_returned` and
`requests_used`.

Truncate and say so; never refuse, and never return a partial list that reads as complete.
This is Phase 3's principle that silence must not look like an answer, applied to cost
rather than to context.

## Output shapes

`catalog-search`, per item:

```json
{"id": "00000",
 "collection": "building",
 "self": "https://stac.overturemaps.org/2026-08-19.0/buildings/building/00000/00000.json",
 "bbox": [-180.0, -84.29460906982422, -86.84698486328125, 14.345832824707031],
 "datetime": "2026-08-19T00:00:00Z",
 "properties": {"num_rows": 5007414, "num_row_groups": 256, "storage:schemes": {}},
 "asset_count": 2}
```

wrapped in an envelope carrying `catalog`, `mode`, `items`, `items_returned`,
`requests_used` and `truncated`.

`catalog-assets`, per asset:

```json
{"key": "aws",
 "href": "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/2026-08-19.0/theme=buildings/type=building/part-00000-....zstd.parquet",
 "media_type": "application/vnd.apache.parquet",
 "roles": ["data"],
 "advertised": {"size_bytes": null, "num_rows": 5007414},
 "readable_by": ["duckdb"]}
```

Rules:

- **`properties` passes through verbatim and unwhitelisted.** Collections differ widely,
  `num_rows` on Overture against `eo:cloud_cover` and `proj:epsg` on Sentinel-2, and a
  whitelist would silently drop the field that mattered for a collection nobody anticipated.
- **`advertised` is namespaced deliberately.** Everything under it is the publisher's claim,
  not a measurement. `size_bytes` comes from `file:size` where present and is `null`
  otherwise; other keys are lifted from item properties where the collection supplies them.
  Phase 3 spent real effort making `not_evaluated` distinguishable from "checked and clean";
  this is the same problem, and an advertised `num_rows` must not sit where it could be read
  as a QC metric.
- `bbox` is always lon/lat WGS84. The STAC specification mandates it.
- Missing optional fields are `null`, never absent. Phase 0's field test recorded that an
  absent key reading as `null` is indistinguishable from a genuine `null`; emitting the key
  explicitly at least makes the shape stable.

## readable_by, and its relationship to Phase 6

`readable_by` is a bare media-type lookup: `application/vnd.apache.parquet` and the
GeoParquet media types map to `["duckdb"]`, everything else to `[]`. It is the concrete
mechanism behind the plan's requirement that "Phase 2's query path can consume a GeoParquet
asset href directly".

It is deliberately a **format fact, not a routing decision**. It states what can open the
file, not what should. No size, locality or operation is considered, and nothing chooses.

It is nonetheless planner-shaped, and the plan's D5 defers the execution planner to Phase 6.
**Phase 6 subsumes this field.** When `planner.py` lands, `readable_by` either feeds it as
an input or is replaced by it; it must not become a second, competing routing table. This is
recorded here so Phase 6's review does not have to rediscover it.

## Errors

Three new codes in `llm_gis/errors.py`, joining the existing set:

| Code | Fires when |
|---|---|
| `CATALOG_UNREACHABLE` | DNS failure, connection refused, timeout, or a 5xx from the catalogue |
| `CATALOG_MALFORMED` | a 200 response that does not parse as STAC, or a document missing the fields its `type` requires |
| `ITEM_NOT_FOUND` | HTTP 404 for an item URL |

Each raises `GisError` with a `suggested_action`, rendered as JSON on stderr with exit 1 per
the Phase 1 CLI contract.

HTTP timeout is 30 seconds. **There is no retry logic.** A flaky catalogue should say so
rather than be papered over, per the house rule against defensive programming.

## Testing

Fixture-based by default; nothing in the default run touches the network.

- `tests/fixtures/stac/` — recorded JSON, trimmed to a few KB each: Overture catalog,
  collection and item; a CDSE search response and item; one malformed item.
- `tests/test_stac_shape.py` — every flattener over those fixtures.
- `tests/test_catalog_errors.py` — unreachable and malformed catalogues yield the right code
  and exit 1.
- `tests/test_catalog_budget.py` — traversal driven by a **fake fetcher**: budget exhaustion
  sets `truncated`, cycles terminate, and the extent prefilter demonstrably skips item
  fetches. The prefilter's saving is asserted, not assumed.
- `tests/live/test_catalog_remote.py` — the Example 2 chain whole (Overture traversal, asset
  href, `duck-query` bbox, result written) plus a CDSE search smoke test. Excluded from the
  default run.
- `tests/test_output_contract.py` — extended with the four new commands.

## Documentation

`README.md`, `AGENTS.md` and `.claude/skills/hot-start/SKILL.md` gain the four commands and
the alias list, shipping with the phase per O22.

One footgun needs stating explicitly in all three. **`catalog-search --bbox` is always
lon/lat WGS84, because the STAC specification mandates it. `duck-query --bbox` is in the
data's own CRS.** Two commands, the same flag name, different meanings, designed to be used
back to back. The field test should deliberately exercise an asset in a projected CRS to
find out how badly this bites.

## Done when

The plan's Example 2 runs end to end: Overture STAC, discover a remote GeoParquet asset,
DuckDB bbox query, result written to `/data/outgoing/`, with no ingestion. Then a field
test on a real job through the `bin/*` commands, with findings in `docs/reports/`, per the
plan's standing rule that a phase is not done until one has run.
