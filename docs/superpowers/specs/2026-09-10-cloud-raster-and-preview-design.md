# Phase 7 — Cloud raster and preview: design

**Status:** approved design, not yet implemented.
**Plan reference:** `docs/plans/2026-09-04_improvement_plan_revised.md`, "Phase 7 — Cloud
raster (O6) and preview (O8)".
**Date:** 2026-09-10.

## Purpose

The workspace can discover a Sentinel-2 COG and cannot open it. Phase 4 verified STAC
discovery live against Earth Search and CDSE and recorded that as its known limitation;
Phase 6 left raster the one format in the planner's table with no engine, refusing with
"Cloud raster arrives in Phase 7". This is that phase.

It adds a third reader — GDAL, reading a COG in place over HTTP range requests — and a
picture. `bin/inspect` learns remote URIs, `bin/raster-window` reads an area of interest out
of a cloud raster without downloading it, and `bin/preview` renders any dataset to a
deterministic PNG that a vision-capable model can check for the failures numbers hide.

**Done when:** the original's Example 3 runs — STAC, COG, remote inspect, AOI window read,
statistics, derived output — without downloading the full raster.

## The finding that shapes this phase

The plan specifies `rasterio` (`uv add rasterio`). It is not needed. Every capability Phase 7
requires is already present in the image we ship, `ghcr.io/osgeo/gdal:ubuntu-small-3.13.3`.

Measured on 2026-09-10 inside `docker compose run --rm agent`, against a live Earth Search
Sentinel-2 L2A asset (`S2A_32TMR_20230605_0_L2A/B04.tif`, 10980x10980, EPSG:32632, roughly
150 MB):

| Capability | Command | Result |
|---|---|---|
| Remote inspect | `gdalinfo -json /vsicurl/<href>` | 9.4s; full CRS, geotransform, `LAYOUT=COG` |
| Approximate statistics, whole raster, remote | `gdalinfo -json -approx_stats /vsicurl/<href>` | 11.0s; reads overviews, not the full raster |
| Windowed read and COG export | `gdal_translate -projwin ... -of COG` | 13.2s; **478 KB written** |
| Exact statistics on the window | `gdalinfo -json -stats <window>` | instant; min 253, max 16536, mean 7635 |
| Zonal statistics, direct against the remote COG | `gdal raster zonal-stats -i /vsicurl/<href> --zones ...` | 4.4s; values identical to the same run against a local clip |
| Raster PNG render | `gdal_translate -of PNG -ot Byte -scale <min> <max> 0 255 -outsize 512 0` | 0.15s from the window |
| Vector PNG render | `gdal_create` canvas, `gdal_rasterize -b <n> -burn 255`, `gdal_translate -of PNG` | valid 512x512 RGB PNG |

The venv holds `numpy 2.5.2`, `shapely 2.1.2` and `geopandas 1.1.4`; it holds no `rasterio`,
no `matplotlib` and no `PIL`, and it does not see the image's own `osgeo.gdal`. Adding
`rasterio` from PyPI would place a second GDAL and PROJ stack beside the image's, to be kept
in step, in exchange for capabilities we already have. See D8.

## What this phase does not do

Recorded first, because a raster module accretes ambition faster than it accretes commands.

- **It does not download.** Every remote read goes through `/vsicurl` range requests. A full
  download happens only when the caller asks for one by name, and the name is `--materialise`,
  which routes to the existing `ingest-raster`.
- **It does not do band math.** No NDVI, no index computation, no multi-asset alignment.
  Two assets windowed to a common grid is Example 4's problem ("remote dataset A / remote
  dataset B / subset both") and belongs to the phase that takes Example 4 on. Decided, not
  forgotten.
- **It does not give raster an `analyse` route.** SQL across sources needs the persistent
  workspace, and `qc_collect._table_raster_metrics` is structural-only because pixel
  statistics over a tiled PostGIS raster table were deferred. `--zones` answers "give me a
  number by area" without a database, so `analyse` on a raster stays refused, naming `--zones`
  as the alternative.
- **It does not add a dependency.** See the table above and D8.
- **It does not serve tiles.** Rendering writes a file with `gdal_translate` and
  `gdal_rasterize`. No server, no basemap asset, no network call to draw.

## Modules

Two new, three extended, one that improves without being edited.

- **`llm_gis/raster.py`** (new). The windowed read and what hangs off it: window, reproject,
  statistics, zonal statistics, COG export. Shells out through the existing `run_command`,
  parses JSON, returns dicts. It knows nothing about the CLI and nothing about rendering.
- **`llm_gis/preview.py`** (new). Framing and rendering only: compute the frame, burn the
  channels, write the PNG and its sidecar. It takes metrics as an argument and never collects
  them itself.
- **`llm_gis/inspect.py`** (extended). Accepts a remote URI. Today it refuses on
  `input_path.exists()` before anything else runs; that guard applies to local paths only.
  A remote asset gets `Provenance(REMOTE_URI)` rather than `LOCAL_FILE` — the constant is
  already in `asset.py` and is currently unused.
- **`llm_gis/qc_collect.py`** (extended). `file_raster_metrics` gains a remote source and an
  optional AOI window. This is where Phase 3's explicitly deferred "remote URIs as a QC
  source" lands.
- **`llm_gis/planner.py`** (extended). A new strategy constant `GDAL = "gdal"` alongside
  `DUCKDB` and `POSTGIS`, `READERS[RASTER] = [GDAL, POSTGIS]`, and a raster branch in
  `_query_route`. The refusal in `route()` that currently reads "Cloud raster arrives in
  Phase 7" goes with it.
- **`llm_gis/catalog.py`** (untouched). `readers_for()` already delegates to
  `planner.classify()`, so filling the planner's raster row makes every discovered COG report
  `readers: ["gdal", "postgis"]` instead of `[]`, with no edit in this file. Phase 4's known
  limitation closes as a side effect. `readable_by` stays Parquet-only; its docstring already
  says it is deliberately narrower.

One shared helper belongs in `common.py`:

- **`gdal_uri(uri)`** — prefixes `/vsicurl/` for `http://` and `https://`, `/vsis3/` for
  `s3://`, and passes a local path through unchanged. Every GDAL invocation in the workspace
  goes through it, so the VSI convention is stated once rather than sprinkled through call
  sites.

## Commands

```
bin/inspect <path-or-url>                    # extended: remote URIs now allowed
bin/raster-window <source> [AOI] [options]   # new
bin/preview <dataset> [--aoi ...]            # new
```

The surface stays flat, one verb per command, as every existing command is.

### bin/raster-window

The AOI is given one of two ways:

- `--bbox minx,miny,maxx,maxy` with `--bbox-crs`, **defaulting to EPSG:4326 and stated
  explicitly**. Inheriting the source CRS would silently accept degrees against a UTM raster,
  which is the swapped-coordinate failure `bin/preview` exists to catch. The default is
  written into the help text and echoed in the result.
- `--aoi <vector>` to take a vector file's extent.

Then: `--band` (default 1); `--t-srs` to reproject the window; `--stats/--no-stats` (default
on, exact over the window); `--zones <vector>` with `--zone-stat` (repeatable, defaulting to
`count,mean,min,max,stdev`); `--output <path>` to write a COG; `--ingest-id` for the manifest.

The result is the usual `_emit` envelope, carrying the window bbox in native CRS and in 4326,
the CRS, the size, band statistics, zonal rows when asked, the output path when one was
written, and a `bytes_read` note.

### bin/preview

`<dataset>` is any local or remote raster or vector. `--aoi` is optional. `--output` defaults
under `/data/outgoing/`. It writes `<name>.png` and `<name>.preview.json`.

## Materialise, in raster's vocabulary

Phase 6 routes on one axis: whether the result has to outlive the command that made it. Raster
keeps that axis and spells it at two levels.

- **In `bin/plan`.** `--materialise` on a raster query routes to `ingest-raster`, which loads
  the raster into PostGIS where later `run-sql` steps can reach it. Without it, the route is
  `bin/raster-window`. Same shape as the vector rule, same `fallback` block.
- **In `bin/raster-window`.** With no `--output`, nothing is written: statistics and zonal
  statistics both run straight off `/vsicurl`. `--output` is the caller's explicit request for
  pixels that survive the command.

"Materialise only when required" is therefore not a heuristic anywhere in this phase. It is
the absence of a flag the caller did not type.

### The planner's raster rules

| operation | `--materialise` | route | reason |
|---|---|---|---|
| query | no | GDAL | a COG is read in place through range requests; no persistence was requested |
| query | yes | POSTGIS | the pixels must survive this command, and the workspace is where results live |
| export | — | GDAL | the source never enters the database |
| analyse | — | refused | SQL across sources needs the workspace; use `--zones` for statistics by area |

Remote raster carries a warning of its own, and it is the **opposite** of the existing
`REMOTE_UNINDEXED_READ` that remote vector carries: a remote COG read is efficient, 478 KB
pulled from a 150 MB scene. Saying so explicitly stops a reader generalising "remote is slow"
from the vector rule onto this one.

## Data flow: Example 3, end to end

```
bin/catalog-search   ->  item                                    (Phase 4, unchanged)
bin/catalog-assets   ->  href, readers: ["gdal", "postgis"]      (improves for free)
bin/inspect <href>   ->  CRS, size, geotransform, LAYOUT=COG     (9.4s, no download)
bin/raster-window <href> --bbox ... --stats --output aoi.tif
                     ->  478 KB COG, band statistics, manifest
bin/preview aoi.tif --aoi aoi.gpkg
                     ->  PNG and sidecar for visual confirmation
```

No step in that chain downloads the scene. The done-when is a property of the design, not an
outcome to be hoped for.

## Preview's render contract

One command, two render paths, one framing rule.

**Framing**, shared by both paths: the frame is the union of the dataset bbox and the AOI
bbox, reprojected to EPSG:4326 with `qc.reproject_bbox` — which already densifies edges so a
curved edge is not clipped — then padded 5% and squared to 512x512. Without `--aoi` the frame
is the dataset alone, still in 4326, still with the graticule.

**Channels**, shared by both paths: red is the data, green the AOI outline, blue whole-degree
graticule lines. The canvas is built with `gdal_create -bands 3 -burn 0`, filled with
`gdal_rasterize -b <n> -burn 255`, and written with `gdal_translate -of PNG`.

- **Vector data.** Reprojected with `ogr2ogr -t_srs EPSG:4326` and burned filled into red. The
  AOI is additionally converted with `-nlt MULTILINESTRING` so it reads as an outline rather
  than a blob covering what it is meant to frame.
- **Raster data.** `gdal_translate -of PNG -ot Byte -scale <min> <max> 0 255 -outsize 512 0`
  into red, with the AOI and graticule burned over it.

The graticule is computed and drawn, never downloaded. This is what lets one picture show all
three failures the plan names: a swapped-coordinate dataset sits at the wrong graticule
intersection, an empty intersection shows two shapes with clear space between them, and
features far from the AOI show as a small AOI box beside a sprawling dataset.

**Determinism** is the point, so it is a property rather than an aspiration. The frame comes
from measured bboxes; the output size is fixed; the resampling is named; and the raster
`-scale` bounds come from the measured window statistics, never from a per-run heuristic. The
same input produces the same PNG, byte for byte. Every one of those values goes into the
sidecar, so the render is re-derivable from the JSON alone:

```json
{
  "dataset": {"uri": "...", "kind": "raster"},
  "frame": {"bbox_4326": {"minx": 0, "miny": 0, "maxx": 0, "maxy": 0},
            "size": [512, 512], "resampling": "nearest"},
  "render": {"channels": {"r": "data", "g": "aoi", "b": "graticule"},
             "scale": {"min": 253, "max": 16536},
             "graticule_degrees": 1},
  "summary": {"crs": "...", "bbox": {"minx": 0, "miny": 0, "maxx": 0, "maxy": 0},
              "bbox_4326": {"minx": 0, "miny": 0, "maxx": 0, "maxy": 0},
              "bands": [{"index": 1, "min": 253, "max": 16536, "mean": 7635}],
              "aoi_intersects": false}
}
```

`aoi_intersects` is the machine-readable form of the failure the picture exists to show. The
picture and the number agree, or the fault is in our code rather than in the data.

### Preview and QC

They stay separate commands and share their collectors. `qc.py` is judgement over metrics;
`qc_collect.py` gathers them. `preview.py` calls the same collectors for its `summary` block
and renders; `bin/qc` calls them and judges. Neither module imports the other. The raster
metrics `file_raster_metrics` already computes are reused rather than reimplemented, and
extending those collectors to accept a remote URI and an AOI window is what closes Phase 3's
deferred item.

## Errors

The existing codes carry most of this — `INPUT_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `CRS_MISSING`,
`CRS_SUSPICIOUS`. Three situations need naming.

- **Zone CRS mismatch.** `gdal raster zonal-stats` warned "Inputs and zones do not have the
  same SRS" and computed anyway: a GeoJSON holding UTM coordinates was read as EPSG:4326. The
  values happened to be correct; they need not have been. So `raster-window --zones` compares
  the two CRSs itself and reprojects the zones explicitly before handing them to GDAL, rather
  than trusting a warning we would have to parse out of stderr.
- **An AOI outside the raster.** Not an error. The command returns a result with
  `aoi_intersects: false` and empty statistics, because an empty intersection is a finding —
  one of the three this phase is built to surface.
- **A failed remote read.** `/vsicurl` failures surface as GDAL stderr. They map to a single
  code carrying the URI and the HTTP status in `details`, so a 403 on a requester-pays bucket
  does not read as a malformed file.

## Testing

Fixtures by default, live excluded, as every phase since Phase 0.

A small COG committed to `tests/fixtures/` beside the existing `elevation.tif` covers
windowing, statistics, zonal statistics, framing and rendering with no network. The planner's
whole raster table tests with no network and no database, because `classify` still opens
nothing and the module stays pure. `tests/live/test_raster_remote.py` carries the `/vsicurl`
Sentinel-2 path, marked `live` and excluded from the default run, shaped like the existing
`tests/live/test_catalog_remote.py`. Example 3 itself is a live field test, reported the way
Phase 4's was.

## Build order

Seven increments, each independently mergeable, each leaving the tree working.

1. `gdal_uri()` in `common.py`, and remote URIs in `bin/inspect`. Closes Phase 4's known
   limitation on its own.
2. The planner's raster row and rules. Pure, tested offline. `bin/catalog-assets` improves
   with no edit in `catalog.py`.
3. `raster.py`: windowed read, statistics, COG export, exposed as `bin/raster-window`.
4. `--zones`, with our own CRS check in front of it.
5. `qc_collect` remote and windowed raster metrics. Closes Phase 3's deferred item.
6. `preview.py` and `bin/preview`: the raster path, then the vector path.
7. Documentation — `README.md`, `AGENTS.md`, `.claude/skills/hot-start/SKILL.md` — and the
   live Example 3 field test.

Increments 1 and 2 are worth landing first whatever happens to the rest: between them they
close a Phase 3 and a Phase 4 loose end, and they cost almost nothing.

## Decisions for the log

**D8 — no `rasterio`.** The plan specifies `uv add rasterio`. The image's own GDAL 3.13.3
performs every Phase 7 capability, measured on 2026-09-10 and tabulated above: remote inspect,
overview-based approximate statistics without a full download, windowed read and COG export
writing 478 KB from a 150 MB scene, exact statistics on the window, zonal statistics straight
against the remote COG with values identical to a local clip, and PNG rendering. A PyPI
`rasterio` wheel would put a second GDAL and PROJ stack beside the image's, to be kept in
step, and would buy none of it. Exposing the image's `osgeo` bindings into the venv through
system site packages avoids the double stack but breaks the venv's isolation and buys none of
it either.

**D9 — accepted risk on the provisional `gdal` CLI.** `gdal raster zonal-stats` belongs to
GDAL's unified command line interface, which prints that it is "provisionally provided" and
that the project "reserves the right to modify, rename, reorganize, and change the behavior of
the utility until it is officially frozen in a future feature release". We pin
`ghcr.io/osgeo/gdal:ubuntu-small-3.13.3` exactly, so nothing moves underneath us. The exposure
is one command, and a future image bump must re-verify it. Everything else in this phase uses
the frozen classic utilities.
