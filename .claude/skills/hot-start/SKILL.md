---
name: hot-start
description: Instant project context for llm-gis - a headless PostGIS+GDAL geospatial backend. Use when you need architecture or workflow details about this project: ingestion, spatial SQL, export, bin/ commands, PostGIS, GDAL, ogr2ogr, or GeoPackage.
---

# llm-gis Hot Start

You are working on **llm-gis**: a headless geospatial analysis backend. It ingests vector/raster data into PostGIS, runs spatial SQL, and exports results as GeoPackage or GeoJSON. Every operation is a non-interactive CLI command returning JSON on stdout. It runs entirely in Docker.

## Architecture (3 layers)

1. **Shell wrappers** (`bin/`): each calls `docker compose run --rm agent uv run llm-gis <cmd> "$@"`. This is the only interface.
2. **Typer CLI** (`llm_gis/cli.py`): registers all subcommands, parses args, delegates to modules, prints JSON.
3. **Module functions** (`llm_gis/*.py`): one file per capability. All share `llm_gis/common.py` for DB connection, SHA-256 hashing, subprocess execution, path sanitization, CRS validation.

## Tech stack

- Python 3.12, `uv` package manager, Typer CLI, psycopg 3, Pydantic 2
- PostgreSQL 17 + PostGIS 3.5 + postgis_raster
- GDAL 3.9.3 (ogr2ogr, ogrinfo, gdalinfo, gdalwarp, raster2pgsql)
- Docker Compose (two services: `db` and `agent`)
- Build backend: hatchling

## The asset descriptor

`llm_gis/asset.py` holds `Asset`, the one shape `inspect`, `duck-describe` and
`catalog-assets` all build internally. Top-level fields carry measurements only;
a publisher's claims stay under `advertised` and are never promoted. Provenance
travels with the asset: source type, retrieval time, catalogue and item id where
applicable, and a `content_hash` slot that only producers which already hash
their input fill. Each command serializes the asset back to its own historic JSON
keys, so the descriptor is internal and no output changed when it landed.

## Commands

| Command | Purpose |
|---------|---------|
| `bin/doctor` | Verify DB connectivity and tool versions |
| `bin/inspect <path>` | Inspect dataset: CRS, geometry type, extent, feature count |
| `bin/stage <path>` | Hash + copy input to staging, returns `ingest_id` |
| `bin/ingest-vector <path> --table <name> [--src-crs] [--dst-crs]` | Load vector into PostGIS via ogr2ogr |
| `bin/ingest-raster <path> --table <name> [--src-crs] [--dst-crs]` | Load raster into PostGIS via raster2pgsql |
| `bin/list-ingestions [--limit N]` | List past ingestions from meta.ingestions |
| `bin/describe-table <schema.table>` | Column names, types, row count |
| `bin/run-sql <file> --ingest-id <id> [--statement-timeout 5min]` | Execute SQL with controlled search_path |
| `bin/export <path> --format gpkg\|geojson --table <schema.table>` | Export table to file |
| `bin/export <path> --format gpkg\|geojson --sql "SELECT ..."` | Export query to file |
| `bin/qc <path-or-table> [--expect-non-empty] [--metric-op] [--compare-to <ref>] [--id-column <c>] [--exact-stats]` | Deterministic metrics and warnings for a dataset or table |
| `bin/catalog-collections <catalog>` | Collections a STAC catalogue offers |
| `bin/catalog-search <catalog> [--collection] [--bbox] [--datetime] [--limit]` | Find items by area and time |
| `bin/catalog-item <item-url>` | One STAC item |
| `bin/catalog-assets <item-url> [--role] [--media-type]` | Asset hrefs, advertised metadata, and what can read them |
| `bin/plan <query\|analyse\|export> <source> [--bbox] [--where] [--materialise] [--engine]` | Explain which engine (duckdb/postgis/gdal) should run a job, why, and the exact steps. Executes nothing |
| `bin/raster-window <path-or-url> --bbox <minx,miny,maxx,maxy> [--bbox-crs] [--t-srs] [--zones <vector>] [--zone-stat] [--output <path>]` | Read an AOI out of a raster (local file or remote COG) without downloading the scene |
| `bin/preview <path-or-url> [--aoi <vector>] [--output <path-stem>]` | Render a dataset to a deterministic PNG with an AOI outline and graticule, plus a `.preview.json` sidecar |

## Standard workflow

```
1. bin/inspect /data/incoming/<file>          -> check crs_status
2. bin/ingest-vector ... --table X --dst-crs EPSG:3035  -> note ingest_id
3. bin/describe-table raw_<ingest_id>.X       -> get exact column names
4. Write SQL to /data/work/<ingest_id>.sql    -> MUST start with CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;
5. bin/run-sql /data/work/<ingest_id>.sql --ingest-id <ingest_id>
6. bin/describe-table analysis_<ingest_id>.result_table  -> verify
7. bin/export /data/outgoing/result.gpkg --format gpkg --table analysis_<ingest_id>.result_table
   -> returns a "qc" block by default (--no-qc to skip)
8. Read qc.warnings and report anything there to the human in plain terms before declaring the job done.
```

## Quality control

QC reports metrics and, where the caller declared enough context, warnings.

| Code | Meaning |
|---|---|
| `CRS_MISSING` | No CRS on the dataset |
| `CRS_SUSPICIOUS` | The CRS does not match the extent (lon/lat values in a projected CRS, or the reverse) |
| `GEOGRAPHIC_CRS_FOR_METRIC_OPERATION` | Areas or distances requested from degree-based coordinates. Needs `--metric-op` |
| `EMPTY_RESULT_UNEXPECTED` | Zero features where features were expected. Needs `--expect-non-empty` |
| `RESULT_BBOX_DISJOINT_FROM_INPUT` | The result lies nowhere near its input. Needs `--compare-to` |

A check `result` of `not_evaluated` means it was skipped for want of context, not that it passed. Pass the flags when you know the answer, and read `not_evaluated` as "nobody checked".

`CRS_MISSING` and `CRS_SUSPICIOUS` are advisory in a QC result (exit 0) and fatal in `ingest-vector` / `ingest-raster` (exit 1). Same names, different force.

`export` runs QC over what it wrote unless `--no-qc` is given. For a `--sql` export, pass `--compare-to <source table>` or the extent check cannot run.

## STAC discovery

Catalogue aliases: `overture` (GeoParquet, static catalogue), `cdse` (Sentinel-2, search
API, anonymous search but downloads need an account), `earth-search` (Sentinel-2, search
API). Any https URL also works.

Discovery never downloads. The chain is: `catalog-search` to find items, take an item's
`self` href, `catalog-assets` on it, then hand a `readable_by: ["duckdb"]` href straight
to `duck-query`. Nothing is staged or ingested.

**`catalog-search --bbox` is lon/lat WGS84. `duck-query --bbox` is in the data's own CRS.**
Same flag name, different meaning, and they are designed to be used back to back.

A COG asset now reports `readers: ["gdal", "postgis"]` (not `readable_by`, which stays
Parquet-only): hand its href straight to `bin/raster-window` for an AOI read, or to
`bin/inspect` for a header-only look. Values under an asset's `advertised` key are the
publisher's claims, not measurements.

## Cloud raster (GDAL, no rasterio)

`llm_gis/raster.py` shells out to the GDAL 3.13.3 command line already in the image —
`gdalinfo`, `gdal_translate`, `gdalwarp`, `gdal raster zonal-stats` — through
`common.gdal_uri`, which prefixes `/vsicurl/` for `http(s)://` and `/vsis3/` for `s3://`
and passes a local path through unchanged. `rasterio` was deliberately not added (decision
D8): the image's own GDAL already does everything this module needs, and a second PyPI
GDAL/PROJ stack would buy nothing.

A window is a VRT describing the AOI (`-projwin`/`-te`), not a copy — under 2 KB, and no
pixel is read from the source until something (`gdalinfo -stats`, `gdal raster
zonal-stats`, `gdal_translate` with `--output`) actually reads that VRT. **`--output` is
the only thing in this phase that writes pixels to disk.** Without it, `bin/raster-window`
runs statistics and zonal statistics straight off `/vsicurl` and writes nothing.

`gdal raster zonal-stats` is GDAL's provisional unified CLI (decision D9) and the *only*
GDAL call in this workspace that uses it — everything else uses a classic utility, pinned
against `ghcr.io/osgeo/gdal:ubuntu-small-3.13.3` so nothing moves underneath. Before
handing zones to it, `raster.zonal_stats` compares the zone vector's CRS to the raster's
own and reprojects with `ogr2ogr -t_srs` when they differ, rather than relying on GDAL's
own SRS-mismatch warning (which computes anyway rather than refusing).

`bin/preview` (`llm_gis/preview.py`) frames a dataset and its optional AOI as the union of
their bboxes in EPSG:4326, padded 5% and squared to 512x512, then burns three Byte
channels — red the data, green the AOI outline, blue a whole-degree graticule — built with
`gdal_create`/`gdal_rasterize`/`gdalwarp` and stacked with `gdalbuildvrt -separate` before
a single `gdal_translate -of PNG`. It calls the same `qc_collect` collectors `bin/qc`
judges, so a preview's `summary` block and a `qc` report agree by construction. The render
is deterministic: same input, byte-identical PNG, because the scale bounds come from
measured statistics rather than a per-run guess.

## Hard constraints (non-negotiable)

- **`data/incoming/` is read-only.** Never write files there. All produced files (merged, exported, processed) go to `data/outgoing/`.
- **Column names are always lowercase.** ogr2ogr lowercases on load. Never use mixed-case in SQL.
- **Geometry column is `geom`, primary key is `fid`.** Set at ingest. Use these in all SQL.
- **Analysis schema is NOT auto-created.** SQL files MUST begin with `CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;`
- **CRS must be resolved before ingesting.** If `crs_status` is `missing` or `suspicious`, pass `--src-crs EPSG:XXXX`.
- **Use a projected CRS for metric work.** Buffers, areas, distances need metric CRS. Use EPSG:3035 (Europe) or appropriate UTM zone.

## Ingest ID format

`YYYYMMDDHHMMSS_<first10ofSHA256>` (e.g., `20260226174050_d9d4a9f8b2`)

Schemas derived from it:
- Raw data: `raw_20260226174050_d9d4a9f8b2`
- Analysis: `analysis_20260226174050_d9d4a9f8b2`

## Data paths

| Host | Container | Access |
|------|-----------|--------|
| `data/incoming/` | `/data/incoming` | read-only |
| `data/work/` | `/data/work` | read/write |
| `data/outgoing/` | `/data/outgoing` | read/write |
| `./` (repo root) | `/workspace` | read/write |

## Database

- Default credentials: `gis/gis@db:5432/gis` (no .env needed)
- `DATABASE_URL` overrides individual PG vars if set
- Auto-initialized on first boot: PostGIS extensions, meta schema, ingestions table
- DB init scripts: `docker/db/init/00_extensions.sql`, `docker/db/init/10_schemas.sql`

## Key internals (for code changes)

| File | Role |
|------|------|
| `llm_gis/cli.py` | All Typer subcommand definitions |
| `llm_gis/common.py` | DB connection (`pg_dsn`, `pg_gdal_dsn`), `sha256_for_path`, `run_subprocess`, `sanitize_identifier`, `validate_crs` |
| `llm_gis/inspect.py` | Dataset inspection via ogrinfo/gdalinfo, CRS status logic |
| `llm_gis/ingest_vector.py` | Vector ingest: ogr2ogr + ST_MakeValid + ST_Force2D + GIST index |
| `llm_gis/ingest_raster.py` | Raster ingest: optional gdalwarp then raster2pgsql pipeline |
| `llm_gis/run_sql.py` | SQL execution with search_path preamble via psql subprocess |
| `llm_gis/exporter.py` | Export to GeoPackage/GeoJSON via ogr2ogr; attaches a QC block by default |
| `llm_gis/qc.py` | QC context, the five check functions, report envelope, dispatch |
| `llm_gis/qc_collect.py` | QC collectors: file (GDAL + DuckDB) and PostGIS table metrics |
| `llm_gis/planner.py` | which engine runs a job and why. Pure: classifies a URI by suffix and scheme, applies a small rule table whose only axis is whether the result must outlive the command, and renders the decision as a `bin/*` step list. `bin/plan` prints it and executes nothing. `planner.readers` is the single authoritative format-to-engine table; `catalog.readable_by` is a projection of it. |
| `docker-compose.yml` | Service definitions, volume mounts, env vars, health checks |
| `docker/agent/Dockerfile` | Agent image: GDAL base + postgresql-client + uv |

## What run-sql does behind the scenes

It prepends a preamble before your SQL:
```sql
SET statement_timeout = '5min';
SET search_path TO analysis_<id>, raw_<id>, public;
```
This means your SQL can reference raw tables without schema qualification. Output is logged to `/data/work/logs/<id>/run-sql.log`.

## Security patterns in the code

- All dynamic SQL uses `psycopg.sql.Identifier` and parameterized queries, never f-strings
- `sanitize_identifier()` lowercases and strips non-alphanumeric chars before any identifier hits SQL

## Setup from scratch

```bash
docker compose up -d --build
bin/doctor
```

## No tests exist yet

There is no `tests/` directory. `bin/doctor` is the smoke test. Live test results documented in `docs/reports/`.
