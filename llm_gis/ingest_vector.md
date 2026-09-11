# ingest_vector.py

## What it does

Loads a vector file into PostGIS: creates a raw schema, runs `ogr2ogr` to
copy the data in, then repairs invalid geometries and adds a spatial index.
This is the step that turns a file in `data/incoming/` (or staged in
`data/work/`) into a queryable table.

## When you'd call it

Via `bin/ingest-vector <path> --table <name> [--src-crs] [--dst-crs] [--ingest-id] [--schema]`
— after `bin/inspect` has confirmed the CRS is trustworthy (or you're
supplying `--src-crs` because it isn't).

## Key functions

- `ingest_vector(input_path, table, ingest_id, src_crs, dst_crs, schema)` —
  the whole operation:
  1. Hashes the input, resolves an `ingest_id` (reused if given, else
     `make_ingest_id`).
  2. Calls `inspect_dataset` internally; **refuses to proceed** (raises
     `CRS_MISSING`/`CRS_SUSPICIOUS`) if the CRS is missing or suspicious and
     no `--src-crs` was supplied.
  3. Creates schema `raw_<ingest_id>` (or `--schema`) if absent.
  4. Runs `ogr2ogr -f PostgreSQL ... -nln <schema>.<table> -nlt PROMOTE_TO_MULTI
     -lco GEOMETRY_NAME=geom -lco FID=fid -overwrite`, with `-s_srs`/`-t_srs`
     when given.
  5. Repairs geometry: counts invalid rows, runs
     `UPDATE ... SET geom = ST_Force2D(ST_MakeValid(geom)) WHERE NOT ST_IsValid(geom)`,
     recounts, and creates a `GIST` index on `geom`.
  6. Records the ingestion in `meta.ingestions` (upserted by `ingest_id`) and
     writes `data/work/reports/<ingest_id>.json`.
- `_ogr_command(...)` — builds the `ogr2ogr` argv.

## Fixed conventions this module enforces

Geometry column is always `geom`, primary key is always `fid`, table names are
sanitized to lowercase via `common.sanitize_identifier` — these are the hard
constraints the rest of the codebase (SQL in `run_sql.py`, QC's vector
queries) all assume hold.

## How it fits the overall flow

The vector half of the ingestion step, right after `bin/inspect`
(step 2 of the standard workflow) and before `bin/describe-table` /
`bin/run-sql`. `planner.py`'s generated plans reference this same
`stage` → `ingest-vector` sequence for any local vector file that needs to
outlive a single command. `ingest_raster.py` is its raster counterpart,
sharing most of the same shape (inspect-gate, schema creation,
`meta.ingestions` upsert).
