---
name: hot-start
description: Use when working in the llm-gis repo or handling its geospatial ingestion, SQL analysis, or export workflow, especially when the task mentions PostGIS, GDAL, ogr2ogr, GeoPackage, KML, KMZ, or the bin/ CLI commands.
---

# llm-gis Hot Start

llm-gis is a headless geospatial backend. It ingests vector and raster data into PostGIS, runs spatial SQL, and exports results as GeoPackage or GeoJSON. Every operation is a non-interactive CLI command that returns JSON on stdout and runs through Docker.

## Core structure

1. `bin/` shell wrappers are the only interface. Each runs `docker compose run --rm agent uv run llm-gis <cmd> "$@"`.
2. `llm_gis/cli.py` defines the Typer commands and prints JSON.
3. `llm_gis/*.py` implements capabilities, with shared helpers in `llm_gis/common.py`.

## Main commands

- `bin/doctor`
- `bin/inspect <path>`
- `bin/stage <path>`
- `bin/ingest-vector <path> --table <name> [--src-crs] [--dst-crs]`
- `bin/ingest-raster <path> --table <name> [--src-crs] [--dst-crs]`
- `bin/list-ingestions [--limit N]`
- `bin/describe-table <schema.table>`
- `bin/run-sql <file> --ingest-id <id> [--statement-timeout 5min]`
- `bin/export <path> --format gpkg|geojson --table <schema.table>`
- `bin/export <path> --format gpkg|geojson --sql "SELECT ..."`

## Standard workflow

1. Run `bin/inspect /data/incoming/<file>` and check `crs_status`.
2. Ingest with `bin/ingest-vector` or `bin/ingest-raster`, usually into a projected CRS for metric work.
3. Capture the returned `ingest_id`.
4. Run `bin/describe-table raw_<ingest_id>.<table>` before writing SQL.
5. Write SQL to `/data/work/<ingest_id>.sql`.
6. The SQL must start with `CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;`
7. Run `bin/run-sql /data/work/<ingest_id>.sql --ingest-id <ingest_id>`.
8. Verify with `bin/describe-table analysis_<ingest_id>.<result_table>`.
9. Export with `bin/export`.

## Hard constraints

- Column names are always lowercase after ingest.
- Geometry column is `geom`; primary key is `fid`.
- Analysis schemas are not auto-created.
- If CRS is `missing` or `suspicious`, pass `--src-crs EPSG:XXXX`.
- Use a projected CRS for buffers, area, and distance work. For Europe, prefer `EPSG:3035` unless there is a better local CRS.

## Paths and schemas

- Host `data/incoming/` maps to container `/data/incoming`
- Host `data/work/` maps to container `/data/work`
- Host `data/outgoing/` maps to container `/data/outgoing`
- Repo root maps to `/workspace`
- Raw tables live in `raw_<ingest_id>`
- Derived tables live in `analysis_<ingest_id>`

## Important source files

- `llm_gis/cli.py`
- `llm_gis/common.py`
- `llm_gis/inspect.py`
- `llm_gis/ingest_vector.py`
- `llm_gis/ingest_raster.py`
- `llm_gis/run_sql.py`
- `llm_gis/exporter.py`
- `docker-compose.yml`

## run-sql behavior

`bin/run-sql` prepends:

```sql
SET statement_timeout = '5min';
SET search_path TO analysis_<id>, raw_<id>, public;
```

Your SQL can reference raw tables without schema-qualifying them. Logs go to `/data/work/logs/<id>/run-sql.log`.
