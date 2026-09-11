# common.py

## What it does

The shared foundation almost every other module imports from: database
connection strings, hashing, subprocess execution with credential redaction,
path safety, and CRS parsing/normalization/classification. No `bin/*` command
maps to this module directly — it has no public API surface of its own beyond
these utilities.

## When you'd call it

You don't call it from the CLI. You reach for it when writing or reading any
other module: any file that shells out to GDAL, talks to PostGIS, or needs a
CRS decision goes through here rather than re-implementing the logic.

## Key functions

**Identity and hashing**
- `sanitize_identifier(value)` — lowercases and strips to `[a-z0-9_]`, used
  before any string becomes a SQL schema/table/column name.
- `sha256_for_path(path)` — hashes a file, or a directory by hashing every
  file's relative path + digest in sorted order.
- `make_ingest_id(source_hash)` — `YYYYMMDDHHMMSS_<first10ofSHA256>`.

**Subprocess and remote reads**
- `run_command(args, ...)` — the one subprocess wrapper in the codebase;
  raises `GisError(COMMAND_FAILED, ...)` with redacted stderr/stdout on
  non-zero exit, so no call site handles credentials itself.
- `is_remote(uri)` / `gdal_uri(uri)` — classify a URI's scheme and translate
  it to GDAL's VSI convention (`/vsicurl/`, `/vsis3/`) so every GDAL call in
  the workspace reads remote data as range requests, never a full download.
- `remote_read_error(uri, error)` — turns a generic GDAL non-zero exit into a
  named `REMOTE_READ_FAILED` error with the HTTP status pulled out of stderr.

**Database**
- `pg_dsn()` / `pg_gdal_dsn()` — connection strings for psycopg and for
  GDAL's `PG:` driver, from `DATABASE_URL` or individual `PG*` env vars.
- `db_connect()` — a psycopg connection.

**CRS**
- `parse_crs(value)` / `parse_epsg(value)` — parse EPSG code, WKT, or PROJ
  string via pyproj; `None` if unparseable rather than raising.
- `normalize_crs(crs_text)` — collapses WKT/PROJJSON/EPSG strings to a
  compact `AUTHORITY:CODE` (or passes through unresolvable text).
- `crs_status(crs_text, extent)` — classifies a CRS as `ok`/`missing`/
  `suspicious` given the dataset's extent (the same logic `inspect.py` and
  `qc.py` both rely on).
- `reproject_bbox(bbox, src_crs, dst_crs)` — transforms a bbox dict, used by
  QC's disjointness check and the raster window reader.

**Paths**
- `incoming_root()`, `work_root()`, `ensure_workspace_dirs()`,
  `ensure_child_path()` (refuses a path outside an allowed root — this is
  what keeps `data/incoming/` read-only-by-convention enforced in code),
  `write_json()`, `safe_remove_dir()`.

## How it fits the overall flow

Everything imports this. `planner.py` is the deliberate exception: it
restates `is_remote`'s scheme tuple itself rather than importing it, so the
planner's test suite stays free of `common.py`'s psycopg/pyproj imports and
needs no database.
