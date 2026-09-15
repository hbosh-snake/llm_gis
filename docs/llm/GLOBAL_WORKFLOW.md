# Geospatial work from any folder

## Entry point and paths

Use the installed `~/.local/bin/llm-gis` launcher with the session's original folder
as the shell working directory. Pass **host paths**. Do not change into this repo.
The launcher selects the backend Compose project and mounts inputs at their host
paths. It needs uv and local Docker Compose; setup remains the repo's existing
Docker build/start workflow. `llm-gis doctor` checks the backend.

Relative paths refer to the caller's folder. Requested artifacts use the user's
chosen destination; if none is given, use `./results/`. Preview supplies this
default automatically. Existing files are refused. Sources stay in place;
external sources are never automatically archived.

The caller folder is read-only in the container, with selected output subfolders
writable. Prefer a separate output subfolder: writing into the caller folder
itself, into a source folder, or above a source is refused. A file directly in
HOME needs to be moved into a subfolder before it can be mounted; the launcher
also refuses HOME itself, `/`, and container-owned roots `/data`, `/workspace`,
`/opt`, `/usr`, `/etc`, `/var`, `/proc`, `/sys`, `/dev`, `/root`. Do not retry these
errors by mounting a broader folder.

Legacy `bin/inspect`, `bin/export`, etc. retain their original container-path
behavior when run from the repository. In particular `bin/preview` without an
output still uses `data/work/preview/`. The global launcher injects an explicit
host output instead. Preview filenames replace the stem's last suffix: the stem
`results/parcels.v2` produces `parcels.png` and `parcels.preview.json`.

## Answer questions using evidence

1. Inspect the file the user named. For archives or multilayer datasets, establish
   the intended layer before analysis. If multiple layers fit, ask which to use.
2. Resolve missing/suspicious CRS before ingesting. Use projected metric CRS for
   area/distance/buffers. Explain an unresolved choice in geographic terms.
3. Choose the existing engine: PostGIS for spatial SQL/materialization, DuckDB for
   supported Parquet filters, GDAL raster windows for raster statistics. STAC
   discovery retrieves metadata, not scene downloads.
4. For PostGIS work, ingest the chosen source and describe the exact columns.
   Use `query-sql` for scalar answers and ranked tables. Use `run-sql` to create
   derived tables when needed; its output is execution metadata, not query rows.
5. Base the chat answer on actual returned values. State units, relevant QC
   warnings and truncation. Do not infer that an unevaluated QC check passed.
6. Create a full artifact when requested, independently of the chat preview cap.
   Check the returned QC and link the actual host output path. A failed command
   must not be described as a completed artifact.

Examples (the agent fills in actual schema/table names from the ingest output):

```bash
llm-gis inspect parcels.gpkg
llm-gis ingest-vector parcels.gpkg --table parcels --dst-crs EPSG:3035
llm-gis query-sql --sql 'SELECT count(*) AS parcels, sum(ST_Area(geom)) AS area_m2 FROM raw_ID.parcels'
llm-gis query-sql --sql 'SELECT fid, ST_Area(geom) AS area_m2 FROM raw_ID.parcels ORDER BY area_m2 DESC, fid LIMIT 10'
llm-gis export results/parcels.gpkg --format gpkg --table raw_ID.parcels
llm-gis preview parcels.gpkg
```

Write analysis SQL in a host work file accessible to the launcher. Keep a stable
session cwd across all steps. Stage returns a host staging path that can be read
on the next call. Its generated ingest ID can be passed explicitly to subsequent
ingestion when those operations belong to one workflow.

## Read-only SQL result contract

`query-sql` takes exactly one of `--sql` or `--sql-file`, with optional
`--ingest-id`, `--statement-timeout` (default 5min), `--max-rows` (100),
`--max-bytes` (262144), `--output`, and `--format json|csv`.

It runs SELECT/VALUES (including supported WITH SELECT) in a read-only
transaction through a server-side cursor. SHOW, EXPLAIN and multiple statements
are unsupported. This prevents ordinary writes; it is not a sandbox for hostile
SQL or privileged database functions.

Rows are positional arrays matched to typed column metadata, preserving duplicate
column names. Decimal values are exact strings; dates/times and UUIDs are strings.
Geometry/geography and binary columns are omitted and identified in metadata.
Non-finite numbers become null with a warning. Select spatial values explicitly
as appropriate scalars/text or use the spatial exporter for a complete dataset.

The byte limit measures serialized UTF-8 row bytes, not the entire response.
Maximum preview limits are 10000 rows and 4194304 bytes. A partial preview is
marked truncated; returned_row_count is not the full result count. Full CSV/JSON
export continues past preview limits and reports exported_row_count. CSV empty
fields do not distinguish null from an empty string; JSON preserves that detail.

## Jobs and current limits

Each invocation uses an isolated `data/work/jobs/<uuid>` folder; only its tmp
subfolder is removed on exit. Staging, reports and logs persist so later calls
can use them. Full job cleanup is deferred: large staged sources consume disk
until deliberately removed after their workflow is no longer needed.

For host launcher tests or isolated automation, set `LLM_GIS_JOBS_ROOT` to an
alternate writable directory. The default remains `<repo>/data/work/jobs`.

Generated ingest IDs have a six-hex random suffix. Explicit reuse of ingest IDs
is not locked. Concurrent jobs should use generated IDs and different output
names; races writing the identical output destination are not supported.

DuckDB/raster additional bounded row previews are deferred. Existing raster
statistics remain available; duck-query reports matched counts and can export
its selected rows. Its `--limit` changes the query, not a chat-only preview.
