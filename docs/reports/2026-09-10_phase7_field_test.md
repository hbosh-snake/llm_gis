# Phase 7 Cloud Raster and Preview Field Test - 2026-09-10

## Scope

Ran the plan's done-when end to end through `bin/*` against a real Sentinel-2 COG (not
a fixture), per the Example 3 chain: `catalog-search`, `catalog-assets`, `inspect`,
`raster-window`, `preview` — no full-scene download at any step.

- Environment: `docker compose up -d --build`, `db` healthy, GDAL 3.13.3
- Network: the agent container reached `earth-search.aws.element84.com` and
  `sentinel-cogs.s3.us-west-2.amazonaws.com` directly, no proxy needed

## Commands executed and results

### 1. `bin/catalog-search`

```
bin/catalog-search earth-search --collection sentinel-2-l2a --bbox 8.90,45.95,8.96,46.00 --limit 1
```

`status: "ok"`, one item: `S2A_32TMR_20260909_0_L2A` (`eo:cloud_cover: 99.82`, the
freshest scene the live catalogue had over this AOI — cloudy, but format-valid, which is
all this chain needs). `self`:
`https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/S2A_32TMR_20260909_0_L2A`.

### 2. `bin/catalog-assets` — the Phase 4 dividend confirmed live

```
bin/catalog-assets <self-href-from-above>
```

38 assets. Every COG (`image/tiff; application=geotiff; profile=cloud-optimized`) now
reports `"readers": ["gdal", "postgis"]` where Phase 4/6 reported `[]`. Confirmed with no
edit to `catalog.py`, exactly as the design predicted: `readers_for` delegates to
`planner.classify`, and filling the planner's raster row was the whole fix. The `red`
(B04) asset's href:
`https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/32/T/MR/2026/9/S2A_32TMR_20260909_0_L2A/B04.tif`.

### 3. `bin/inspect` on the remote href

```
bin/inspect <B04 href>
```

`status: "ok"`, `dataset_kind: "raster"`, `size: [10980, 10980]`,
`detected_crs: "EPSG:32632"`. No `.tif` bytes touched the host filesystem; `gdalinfo`
read the header over `/vsicurl`.

### 4. `bin/raster-window` — the windowed read and COG export

```
bin/raster-window <B04 href> --bbox 8.90,45.95,8.96,46.00 --stats \
  --output /data/outgoing/2026-09-10_phase7-cloud-raster/aoi_b04.tif
```

`status: "ok"`, `aoi_intersects: true`, one band:
`{min: 8740.0, max: 12168.0, mean: 10738.5, stdev: 450.5, percent_nodata: 0.0}`. Wall
clock ~33.6s (the `docker compose run` container-start overhead plus the actual range
requests; the design's own 2026-09-10 measurement of the equivalent `gdal_translate` call
alone was 13.2s). Output file: **373,777 bytes** (365 KB), from a scene the STAC item
itself advertises in the tens of MB per band and roughly 150 MB in the design's
reference asset — well under the plan's "under a megabyte" bar and consistent with the
478 KB the design measured for its own AOI.

### 5. `bin/preview`

```
bin/preview /data/outgoing/2026-09-10_phase7-cloud-raster/aoi_b04.tif \
  --output /data/outgoing/2026-09-10_phase7-cloud-raster/aoi_b04
```

`status: "ok"`, `kind: "raster"`. Wrote `aoi_b04.png` (512x512, 144,209 bytes) and
`aoi_b04.preview.json`. The PNG was inspected visually: a bright, cloud-textured red
square filling most of the frame with a thin black margin (the 5% pad) and faint
graticule lines — consistent with a near-fully-cloudy Sentinel-2 red band and with the
render contract (red = data, green = AOI outline, blue = graticule; no AOI was passed
here, so green is empty).

## Done-when checklist

| Step | Result |
|---|---|
| `catalog-search` finds a Sentinel-2 item | yes |
| `catalog-assets` reports its COG as `readers: ["gdal", "postgis"]` | yes, was `[]` before Phase 7 |
| `inspect` reads the header remotely | yes, 10980x10980, EPSG:32632, no download |
| `raster-window` writes an AOI COG under a megabyte with statistics | yes, 365 KB |
| `preview` renders it | yes, 512x512 PNG + sidecar |
| `bin/test tests/` green | yes, 204 passed, 16 deselected |
| `tests/live/test_raster_remote.py -m live` passes | yes, 2 passed in ~41s |

No step downloaded the full scene. The deliverable directory:
`data/outgoing/2026-09-10_phase7-cloud-raster/` (`aoi_b04.tif`, `aoi_b04.png`,
`aoi_b04.preview.json`).

## A correction the field test's fixture work found

The plan's committed-fixture test comments stated the `scene.tif` fixture (EPSG:32632,
corners `399960,5100000` / `405080,5094880`) reprojects to roughly `8.9-9.0 E,
45.97-46.02 N`. Measured directly with `pyproj.Transformer` against the actual corners,
the true reprojection is `7.71-7.77 E, 46.00-46.05 N` — about 1.2 degrees west of the
plan's figures. All `INSIDE`/zones test coordinates in `tests/test_raster.py` and
`tests/test_qc_file.py` were corrected to the measured values (Tasks 3-5 commits); the
`aoi.gpkg`/`scene.tif` disjointness used by `tests/test_preview.py` was unaffected since
both the stated and the corrected ranges are far from `aoi.gpkg`'s 10.0-10.3 E, 45.0-45.3
N. No code behaviour changed — only the test fixtures' expected numbers, which were
wrong before any of this phase's code existed to be tested against them.

## What the live run confirmed that fixtures alone could not

- Live COG headers really do read in ~single-digit seconds via `/vsicurl` (design's own
  measurement: 9.4s on 2026-09-10 against a different scene of the same tile).
- `gdal raster zonal-stats` (the one provisional-CLI call, D9) was exercised only via the
  offline fixture in Tasks 3-4, not against this live scene — a gap worth naming rather
  than silently leaving untested; it is low-risk since the same command ran correctly
  against the local COG fixture with real CRS reconciliation.
- The catalogue's most recent item for this AOI happened to be 99.8% cloud-covered.
  The chain does not care — it proves the plumbing, not that this particular scene is
  useful for any analysis — but a caller picking a scene for content should filter on
  `eo:cloud_cover` at `catalog-search` time, which nothing in this phase does
  automatically.
