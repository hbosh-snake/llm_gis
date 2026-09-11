# raster.py

## What it does

Reads an area of interest (AOI) out of a raster — local file or remote
COG — without downloading the whole scene. A window is described as a VRT
(a small XML file describing which pixels are wanted, typically under 2 KB
for a Sentinel-2 AOI), and statistics or zonal statistics run against that
VRT description. No pixel is actually read until something (`gdalinfo
-stats`, `gdal raster zonal-stats`, or a `gdal_translate` with `--output`)
reads it — a remote scene crosses the network only as range requests over the
window, never a full download. Pixels are only ever *written* to disk when
the caller names an `--output`.

## When you'd call it

Via `bin/raster-window <path-or-url> --bbox <minx,miny,maxx,maxy> [--bbox-crs] [--t-srs] [--zones <vector>] [--zone-stat] [--output <path>]`
— for band statistics or zonal statistics over an AOI, or to materialize a
small COG clip, without staging or ingesting the source raster at all.

## Key functions

- `window(source, bbox, bbox_crs="EPSG:4326", band=1, t_srs=None, stats=True, output=None, zones=None, zone_stats=None, ingest_id=None)`
  — the whole operation: reads the scene's own extent/CRS via `gdalinfo`,
  checks the AOI actually intersects it (returns early with
  `aoi_intersects: false` if not, no VRT built), builds `window_vrt`, reports
  size/native bbox/4326 bbox, optionally computes `band_stats` and/or
  `zonal_stats`, and optionally writes a COG via `gdal_translate` when
  `output` is given.
- `window_vrt(source, bbox, bbox_crs, t_srs, work_dir)` — describes the
  window as a VRT via `gdal_translate -of VRT -projwin_srs ... -projwin ...`
  (or `gdalwarp -of VRT` when `t_srs` is given for reprojection). Writes no
  pixels — a pure description.
- `band_stats(target)` — exact per-band min/max/mean/stdev/percent-nodata
  over whatever the target (the VRT window) covers.
- `zonal_stats(target, zones, stats, work_dir, raster_crs)` — statistics per
  zone via GDAL's `gdal raster zonal-stats` CLI. Reconciles the zone
  vector's CRS against the raster's own CRS itself (`ogr2ogr -t_srs`) before
  calling it, rather than relying on GDAL's own SRS-mismatch warning — which
  computes an answer anyway on a mismatch rather than refusing, a silent-wrong
  failure mode this module avoids by reprojecting first. Field names from
  the zone vector are carried through with `--include-field` so attributes
  ride along in the output.

## How it fits the overall flow

The GDAL query engine for raster sources — the counterpart to `duck.py`/
`query.py` for Parquet and to PostGIS table queries for ingested vector
data. `planner.py` routes any raster source without `--materialise` here.
`qc_collect.file_raster_metrics` imports `window_vrt` directly to scope raster
QC statistics to a bbox.
