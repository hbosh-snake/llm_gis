# Phase 4 STAC Discovery Field Test - 2026-09-07

## Scope

Ran the plan's done-when end to end through `bin/*` against real public STAC catalogues
(not fixtures), per Phase 4's Task 8 gate: the Example 2 chain (Overture STAC, discover a
remote GeoParquet asset, DuckDB bbox query, result written, no ingestion), plus a CDSE
search smoke test, the CRS-footgun exercise, and traversal timing.

- Environment: `docker compose up -d --build`, `bin/doctor` reported `database_ok: true`,
  GDAL 3.13.3, psql 18.6
- Network: the agent container reached `stac.overturemaps.org` and
  `stac.dataspace.copernicus.eu` directly, no proxy needed

## A bug the live run found and fixed before this report

The first run of the Example 2 chain returned zero items for an Oslo bbox that should have
matched. Root cause: Overture's real `building` collection lists its
`extent.spatial.bbox` as exactly one entry per item (`len(bbox) == len(item links)`), with
no leading "overall extent" entry. The design and Task 4's fixtures assumed the documented
STAC convention (overall extent at index 0, one sub-extent per item at indices 1..n), which
Overture's live catalogue does not follow. Slicing off element 0 unconditionally shifted
every sub-extent one position away from the item it actually described, so the prefilter
checked a neighbouring item's bbox and the true match (item `00247`) was never fetched.

Fixed in `llm_gis/stac_fetch.py::_sub_extents` and `llm_gis/catalog.py::flatten_collection`:
both now compare the bbox array's length against the collection's own item-link count to
decide which convention a given document actually uses, and `flatten_collection` computes
the true overall extent from the per-item boxes when no separate entry is present. Two
regression tests added (`tests/test_catalog_budget.py`,
`tests/test_stac_shape.py`), both offline against a fake/synthetic per-item-only shape.
Full offline suite (117 tests) and all 4 live tests pass after the fix. This is recorded
here rather than silently folded into an earlier commit because it changes the meaning of
"standard STAC" the design leaned on — a decision point worth surfacing, not hiding.

## Commands executed and results

### 1. `bin/doctor` and `bin/catalog-collections overture`

```
bin/doctor          -> database_ok: true
bin/catalog-collections overture
```

`mode: "traversal"`, `truncated: false`, `requests_used: 45`, wall clock ~8.1s. Two
collections found: `building` and `building_part`, both under the current release
(`2026-07-22.0` in this response — the walk visits every release it finds as a child of the
root, not only the latest one; see "Traversal timing" below). Both collections report a
`bbox` computed from their per-item extents (there is no separate overall entry in the live
data), consistent with the fix above.

### 2. The Example 2 chain, through the wrappers

```
bin/catalog-search overture --collection building --bbox 10.6,59.8,10.9,60.0 --limit 1
```
`mode: "traversal"`, `requests_used: 23`, `truncated: true` (limit reached), wall clock
~7.1s. One item returned: `00247`, `self`:
`https://stac.overturemaps.org/2026-08-19.0/buildings/building/00247/00247.json`, `bbox`
`[4.51, 59.43, 16.72, 80.04]` (genuinely intersects the Oslo query bbox), `properties`
carrying `num_rows: 4931257` verbatim.

```
bin/catalog-assets <self-href-from-above> --role data
```
Two assets, `aws` and `azure`, both `media_type: "application/vnd.apache.parquet"`,
`readable_by: ["duckdb"]`, `advertised.num_rows: 4931257`, `advertised.size_bytes: null`
(Overture does not publish `file:size`). Wall clock ~6.1s.

```
bin/duck-query <aws-href> --bbox 10.6,59.8,10.9,60.0 --limit 100 \
  --output /data/outgoing/2026-09-07_stac-discovery/buildings.parquet
```
`engine: "duckdb"`, `source_row_count: 4931257`, `matched_row_count: 100` (the limit, not
the true match count — the bbox genuinely contains more than 100 buildings), `crs:
"OGC:CRS84"`, file written. Wall clock ~37.6s — the slowest step by far, expected: this is
DuckDB range-reading a ~5M-row remote Parquet part-file over HTTPS, the cost the STAC layer
exists to let a caller decide about *before* paying it.

```
bin/qc /data/outgoing/2026-09-07_stac-discovery/buildings.parquet --expect-non-empty
```
`qc_status: "ok"`, `warnings: []`, `feature_count: 100`. No ingestion happened at any point
in this chain — confirmed by `bin/list-ingestions` reporting no new rows (not shown; the
chain never called `bin/stage` or `bin/ingest-vector`).

Done-when met: public STAC, discovered GeoParquet asset, DuckDB bbox query, result in
`data/outgoing/2026-09-07_stac-discovery/buildings.parquet`, no ingestion.

### 3. CDSE search smoke test

```
bin/catalog-search cdse --collection sentinel-2-l2a --bbox 10.6,59.8,10.9,60.0 --limit 1
```
`mode: "search"`, `requests_used: 1`, `truncated: true`, wall clock ~14.0s (mostly
pystac-client's own connection setup and the collection's `/queryables` round trip, not
shown as a separate request in `requests_used` since that count is intentionally
search-request-only per the spec). One Sentinel-2 item returned with 47 assets and rich
`eo:`, `sat:`, `view:`, `processing:` properties passed through verbatim.

```
bin/catalog-assets <self-href-from-above> --role data
```
38 data assets, all `image/jp2`, all `readable_by: []` — correctly honest about the Phase 7
gap. All asset hrefs are `s3://eodata/...`, matching the design's finding that CDSE serves
Sentinel-2 but downloads need credentials.

### 4. The CRS footgun, exercised as far as real data allows

The design predicts `catalog-search --bbox` (lon/lat WGS84) and `duck-query --bbox` (the
data's own CRS) will bite when fed the same four numbers against an asset in a projected
CRS. This could not be triggered exactly as scripted: no public catalogue combines a search
API, a projected-CRS collection, and a DuckDB-readable (Parquet) asset. Overture's
GeoParquet is itself in WGS84, so the Example 2 chain's `--bbox` numbers happen to mean the
same thing in both commands by coincidence, not by any invariant the tools enforce. The
Sentinel-2 items returned here carried no `proj:epsg` property in `properties` at all (the
CDSE catalogue's current item shape omits it at the item level, unlike the fixture recorded
during design), and every Sentinel-2 asset is `readable_by: []`, so `duck-query` cannot be
pointed at one regardless of CRS. The footgun is real in principle — the field test could
not manufacture the one dataset shape that would prove it in practice today, and that
absence is itself the finding: nothing currently on offer forces a caller to notice the
difference, which makes the documentation warning (README, AGENTS.md,
`.claude/skills/hot-start/SKILL.md`, `OUTPUT_SCHEMA.md`) the only thing standing between a
future caller and a silent CRS mismatch once a projected-CRS Parquet catalogue exists.

### 5. Traversal timing

| Command | `requests_used` | Wall clock |
|---|---|---|
| `catalog-collections overture` | 45 | ~8.1s |
| `catalog-search overture --collection building --bbox ... --limit 1` | 23 | ~7.1s |

Both walks stayed well under the 200-request budget and finished in single-digit seconds —
an order of magnitude faster than the `duck-query` step that follows them. `docker compose
run --rm` overhead (image already built, container start) accounts for roughly 2-3s of
that; the balance is real HTTP round trips to `stac.overturemaps.org`. **The deferred
document cache under `/data/work/cache/stac/` is not needed yet**: at this speed and this
request count, repeated identical walks would have to run dozens of times per session
before caching paid for its own complexity. This confirms the spec's own prediction.

## What the test suite could not have caught

The extent-alignment bug above is the headline: no offline fixture could have caught it,
because the fixture itself (written from the design's own probe of the "standard STAC"
convention) encoded the wrong assumption. Only a real catalogue's real document shape
exposed it. This is exactly the class of gap Phase 3's field-test rule exists to close, and
it argues for keeping at least one live, content-shape-sensitive assertion (not just
schema-shape) in the live suite going forward, rather than trusting recorded fixtures to
stay representative of catalogues that can and do change their own conventions.

Two smaller observations, neither requiring code changes:
- `catalog-collections overture` walks **all** releases it finds as root's children, not
  only the latest one (`prev`-linked). At two releases today this cost is negligible (45
  requests); if Overture's history of `child`-linked releases grows, this walk could grow
  with it. Worth a future `--latest-only` flag if release history ever gets deep enough to
  matter, but not now — noted as a possibility, not proposed as a change.
- CDSE's current STAC item shape omits `proj:epsg` at the item level even though the design
  spec's probe recorded it there on 2026-09-07. Catalogues evolve; `properties` passing
  through verbatim (rather than a whitelist) meant this shift required no code change to
  keep working correctly — it simply means the field this feeds a QC pre-flight with is not
  guaranteed to be there.

## Deliverable

`data/outgoing/2026-09-07_stac-discovery/buildings.parquet` — 100 Overture buildings near
Oslo, discovered and queried with no ingestion, per the Example 2 done-when.
