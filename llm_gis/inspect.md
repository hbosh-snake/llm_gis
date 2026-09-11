# inspect.py

## What it does

Measures a dataset — local file or remote URI — without ingesting it
anywhere: CRS, geometry type/bands, extent, and feature/band count, read via
`ogrinfo`/`gdalinfo`. This is the read-only diagnostic step that answers "what
am I looking at, and can I trust its CRS?" before anything is written.

## When you'd call it

Via `bin/inspect <path-or-url>` — always the first step against a new source,
and the mandatory gate `ingest_vector.py`/`ingest_raster.py` call internally
before loading anything into PostGIS (ingestion refuses to proceed on a
`missing`/`suspicious` CRS without an explicit `--src-crs` override).

## Key functions

- `inspect_dataset(source, ingest_id=None)` — the whole operation. Tries
  `ogrinfo -json` (vector) then `gdalinfo -json` (raster); whichever
  succeeds decides `dataset_kind`. If neither can read the source, raises
  `UNSUPPORTED_FORMAT` — with a specific hint redirecting a `.parquet` input
  toward `duck-query --format geopackage` instead, since Parquet can't be
  ingested directly. If given, writes the report to
  `data/work/reports/<ingest_id>.json`.
- `_build_vector_asset` / `_build_raster_asset` — turn the raw ogrinfo/
  gdalinfo JSON into an `Asset` (see `asset.py`), computing `crs_status` via
  `common.crs_status` along the way.
- `_to_report(asset)` — flattens the `Asset` back to `inspect`'s historic
  output keys (`input_path`, `detected_crs`, `extent`, `crs_status`,
  `crs_reasons`, plus `layers` for vector or `size`/`bands` for raster).

## How it fits the overall flow

The universal first step. Every ingestion path (`ingest_vector.py`,
`ingest_raster.py`) calls `inspect_dataset` before touching the database, and
propagates its `crs_status`/`detected_crs` into the ingest decision. A remote
source's read failure is translated via `common.remote_read_error` into a
named `REMOTE_READ_FAILED` (HTTP status pulled from GDAL's stderr) rather than
a generic "unreadable file" error.
