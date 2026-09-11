# query.py

## What it does

Deterministic bbox/attribute filters over a Parquet or GeoParquet source,
built to SQL and run through DuckDB. Higher-level than raw SQL on purpose: a
caller states a bbox and an attribute filter as flags, and this module builds
the `SELECT ... WHERE ...` — raw SQL execution stays a separate, explicitly
privileged operation (`run_sql.py`, which only runs against PostGIS).

## When you'd call it

Via `bin/duck-query <uri> [--bbox] [--where] [--columns] [--limit] [--output] [--format parquet|geopackage]`
— to filter a Parquet/GeoParquet source in place (no ingest, no database),
or to materialize a filtered subset as GeoPackage before `ingest-vector`.

## Key functions

- `query(uri, bbox=None, where=None, columns=None, limit=None, output_path=None, output_format="parquet")`
  — the whole operation. Calls `duck.describe(uri)` first to learn the
  geometry column and row count; raises `MISSING_ARGUMENT` if `--bbox` is
  given but the source has no geometry column. Builds and runs a
  `SELECT ... FROM read_parquet(?) WHERE ...` for the count, and a `COPY (...)
  TO ... (FORMAT ...)` for the output file if `--output` was given.
- `_bbox_predicate(column, bbox)` — `ST_Intersects(col, ST_MakeEnvelope(...))`.

## The two bbox coordinate systems — a deliberate footgun to know about

**`--bbox` here is in the source's own native CRS** (whatever `describe(uri)`
reports), not lon/lat WGS84. This is the opposite convention from
`catalog.search_items`'s `--bbox`, which is always WGS84. A bbox taken from
`catalog-search` output must be reprojected to the source's CRS
(`common.reproject_bbox`) before being handed to `duck-query`.

## `--format geopackage`

Writes an ingestible GeoPackage instead of Parquet, using DuckDB's own
bundled GDAL rather than the agent image's GDAL (which has no Parquet driver
and so can't read the source in the first place). This is the conversion path
`planner.py` points to whenever a Parquet source needs `--materialise`: `duck-query
--format geopackage` then `ingest-vector`. If the source has an `fid` column
and no explicit `--columns`, it's excluded from the GeoPackage write, since
GeoPackage assigns its own FID and the two would conflict in DuckDB's GDAL
writer.

## How it fits the overall flow

The query engine for Parquet/GeoParquet sources, whether local or straight
off a STAC `catalog-assets` href. `planner.py`'s `_query_route` routes any
Parquet source here by default (falling back to PostGIS materialisation only
when `--materialise` is requested).
