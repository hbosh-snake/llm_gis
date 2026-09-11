# ingest_raster.py

## What it does

Loads a raster file into PostGIS via `raster2pgsql`, with an optional
`gdalwarp` reprojection pass first. The raster counterpart to
`ingest_vector.py`, sharing the same shape: inspect-gate on CRS, schema
creation, load, record in `meta.ingestions`.

## When you'd call it

Via `bin/ingest-raster <path> --table <name> [--src-crs] [--dst-crs] [--ingest-id] [--schema]`
— after `bin/inspect` has confirmed the raster's CRS is trustworthy.

## Key functions

- `ingest_raster(input_path, table, ingest_id, src_crs, dst_crs, schema)` —
  the whole operation:
  1. Hashes the input, resolves an `ingest_id`.
  2. Calls `inspect_dataset` internally; refuses (`CRS_MISSING`/
     `CRS_SUSPICIOUS`) without `--src-crs` if the CRS can't be trusted —
     the same gate `ingest_vector.py` applies.
  3. If `--dst-crs` is given, reprojects with `gdalwarp` into
     `data/work/staging/<ingest_id>/warped.tif` first; `raster2pgsql` then
     loads that warped file instead of the original.
  4. Creates schema `raw_<ingest_id>` (or `--schema`) if absent.
  5. Shells out to `raster2pgsql -s <srid> -I -C -M <file> <schema>.<table> | psql`
     — `-I` builds a spatial index, `-C` adds raster constraints, `-M`
     vacuum-analyzes afterward.
  6. Reads back band count and pixel size from the file actually loaded
     (`_loaded_dimensions`, via `gdalinfo`).
  7. Records the ingestion in `meta.ingestions` and writes
     `data/work/reports/<ingest_id>.json`.

## How it fits the overall flow

The raster half of the ingestion step. `planner.py`'s generated plans use
`stage` → `ingest-raster` for any raster source that needs to outlive a
single command (`--materialise`); without materialise, raster sources go
through `raster.py`'s `window` reader instead, which never touches the
database.
