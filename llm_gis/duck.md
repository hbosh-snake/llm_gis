# duck.py

## What it does

The DuckDB execution path for Parquet and GeoParquet, local or remote.
Deliberately kept separate from the PostGIS path: DuckDB answers cheap
questions about a dataset without materializing it anywhere, while PostGIS
owns persistent, queryable workspaces. This module holds the connection setup
and the `describe` operation; `query.py` builds on it for filtering.

## When you'd call it

Via `bin/duck-describe <uri>` — the first thing to run against a Parquet or
GeoParquet source (local file, `https://`, or `s3://`) before filtering it
with `bin/duck-query` or ingesting it. Also called internally by
`exporter.py` (to describe a written GeoParquet output) and `qc_collect.py`
(for Parquet metrics).

## Key functions

- `connect()` — an in-memory DuckDB connection with the `spatial` and
  `httpfs` extensions loaded (`httpfs` is what lets DuckDB read `https://`
  and `s3://` URIs directly).
- `describe(uri)` — schema, row count, geometry column, CRS, and bbox of a
  Parquet/GeoParquet source. CRS resolution tries the DuckDB geometry type
  string first (`GEOMETRY('EPSG:4326')`), then falls back to the GeoParquet
  spec's `geo` key-value metadata (defaulting to EPSG:4326 per spec when
  absent).
- `reader_sql(uri)` — picks `read_parquet(?)` vs `ST_Read(?)` by file
  extension. This matters because the agent's GDAL build has no Parquet
  driver (`ST_Read` can't open Parquet) and `read_parquet` can't open a
  GeoPackage — exactly one of the two is ever right.

## How it fits the overall flow

Everything in this module reports what it **measured**, never what a
publisher claims (contrast with `catalog.py`'s `advertised` block). It builds
an `Asset` internally (see `asset.py`) and flattens it back to the historic
`duck-describe` JSON keys. `query.py`, `exporter.py`, and `qc_collect.py` all
import `connect`/`describe`/`reader_sql` from here rather than reconnecting or
re-detecting CRS themselves.
