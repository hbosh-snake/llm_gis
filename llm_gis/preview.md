# preview.py

## What it does

Renders a dataset (and optional AOI) to a deterministic PNG for visual QC —
three failures a number hides that a picture doesn't: coordinates in the
wrong order, an AOI that misses the data entirely, or features nowhere near
the AOI. The frame is always EPSG:4326 with a drawn graticule, so all three
are visible in one image: a wrong graticule cell, clear space between two
shapes, or a small box beside a sprawl. Also writes a `.preview.json` sidecar
carrying the frame parameters and the same summary metrics QC would report.

Nothing here measures — metrics come from `qc_collect`, the same collectors
`bin/qc` judges, so a preview's `summary` block and a `qc` report agree by
construction.

## When you'd call it

Via `bin/preview <path-or-url> [--aoi <vector>] [--output <path-stem>]` — any
time you want a quick visual sanity check of a dataset or of a dataset against
an AOI, at any stage of a workflow (raw file, remote COG, or exported result).

## Key functions

- `render(dataset, aoi=None, output=None)` — the whole operation: measures
  extent (via `qc_collect.file_raster_metrics`/`file_vector_metrics`),
  computes the padded/squared `frame`, builds three single-band Byte
  channels — red the data, green the AOI outline, blue a whole-degree
  graticule — with `gdal_create`/`gdal_rasterize`/`gdalwarp`, stacks them
  with `gdalbuildvrt -separate` (a description, not a copy), and writes one
  `gdal_translate -of PNG`. Cleans up all GDAL intermediates afterward.
- `frame(dataset_bbox, aoi_bbox)` — the rendered extent: union of dataset and
  AOI bboxes, padded 5%, squared to 512×512, floored at a minimum span so a
  single point or single-row raster still renders.
- `_raster_channel(...)` — warps the raster data onto the frame grid and
  scales to Byte using **measured** statistics (band min/max from
  `qc_collect`), never a per-run guess — this is what makes two renders of
  the same input byte-identical.
- `_burn(...)` — reprojects a vector source to 4326 and rasterizes it into a
  channel, as a fill (data) or an outline (AOI).
- `_graticule(box, destination)` — computes whole-degree gridlines as
  GeoJSON directly (not downloaded from anywhere).

## How it fits the overall flow

An optional, any-stage visual QC step alongside `bin/qc`. Shares its metrics
collector (`qc_collect.py`) with `qc.py`, so its `summary` block is guaranteed
consistent with what `bin/qc` would report for the same source.
