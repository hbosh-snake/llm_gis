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

## Standard workflow

```
1. bin/inspect /data/incoming/<file>          -> check crs_status
2. bin/ingest-vector ... --table X --dst-crs EPSG:3035  -> note ingest_id
3. bin/describe-table raw_<ingest_id>.X       -> get exact column names
4. Write SQL to /data/work/<ingest_id>.sql    -> MUST start with CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;
5. bin/run-sql /data/work/<ingest_id>.sql --ingest-id <ingest_id>
6. bin/describe-table analysis_<ingest_id>.result_table  -> verify
7. bin/export /data/outgoing/result.gpkg --format gpkg --table analysis_<ingest_id>.result_table
```

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
| `llm_gis/exporter.py` | Export to GeoPackage/GeoJSON via ogr2ogr |
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
