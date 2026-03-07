---
name: llm-gis
description: Headless PostGIS + GDAL backend for geospatial ingestion and analysis. Use when you need to load, analyze, or export spatial data (vector or raster) in a containerized environment.
---

## Overview

This backend lets you ingest vector and raster datasets into PostGIS, run spatial SQL analysis, and export results as GeoPackage or GeoJSON. Every operation is a non-interactive CLI command that returns JSON on stdout.

All commands are wrappers in `bin/`. They run inside the `agent` Docker container against a PostGIS database (`db`).

## Capabilities

- Inspect vector/raster files (CRS detection, geometry type, extent)
- Ingest shapefiles, GeoPackages, GeoJSON, and raster files into PostGIS
- Reproject on load to any CRS
- Query ingestion history
- Describe any table (columns, types, row count)
- Run spatial SQL files (buffers, intersections, dissolves, zonal stats, distance queries)
- Export PostGIS tables or SQL queries to GeoPackage or GeoJSON

## Hard constraints

**Always follow these — they are not optional:**

- **Column names are lowercase.** `ogr2ogr` lowercases all attribute names. `Name` → `name`, `OBJECTID` → `objectid`. Never quote mixed-case names in SQL.
- **Geometry column is `geom`, primary key is `fid`.** These are set at ingest time. Use them in all SQL.
- **The analysis schema is NOT auto-created.** `run-sql` sets `search_path` but does not create the schema. Your SQL file must start with:
  ```sql
  CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;
  ```
- **CRS must be resolved before ingesting.** If `crs_status` is `"missing"` or `"suspicious"`, pass `--src-crs EPSG:XXXX` to declare the correct CRS.
- **Use a projected CRS for metric work.** Buffer, area, and distance operations require a metric CRS. Use EPSG:3035 (Europe) or the appropriate regional UTM zone.

## Commands

```
bin/doctor
bin/inspect <path> [--ingest-id <id>]
bin/stage <path> [--ingest-id <id>]
bin/ingest-vector <path> --table <name> [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]
bin/ingest-raster <path> --table <name> [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]
bin/list-ingestions [--limit 50]
bin/describe-table <schema.table>
bin/run-sql <sql_file> --ingest-id <id> [--statement-timeout 5min]
bin/export <output_path> --format gpkg|geojson --table <schema.table>
bin/export <output_path> --format gpkg|geojson --sql "SELECT ..."
```

## Standard workflow

```
1. bin/inspect /data/incoming/<file>
   → check "crs_status": "ok" / "missing" / "suspicious"

2. bin/ingest-vector /data/incoming/<file> --table <name> --dst-crs EPSG:3035
   → note "ingest_id" from output

3. bin/describe-table raw_<ingest_id>.<name>
   → read "columns" to know exact column names before writing SQL

4. Write SQL to /data/work/<ingest_id>.sql
   → first line: CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;

5. bin/run-sql /data/work/<ingest_id>.sql --ingest-id <ingest_id>

6. bin/describe-table analysis_<ingest_id>.<result_table>
   → verify table was created and has expected rows

7. bin/export /data/outgoing/<result>.gpkg --format gpkg --table analysis_<ingest_id>.<result_table>
```

## Key output fields

| Command | Key fields to extract |
|---------|----------------------|
| `inspect` | `crs_status`, `crs`, `geometry_type`, `feature_count` |
| `ingest-vector` | `ingest_id`, `schema`, `table`, `status` |
| `list-ingestions` | `ingestions[].ingest_id`, `ingestions[].status` |
| `describe-table` | `columns[].column_name`, `columns[].data_type`, `row_count` |
| `run-sql` | `status`, `statements_executed` |
| `export` | `output_path`, `feature_count` |

## Ingest ID format

`YYYYMMDDHHMMSS_<first10ofSHA256>` — e.g. `20260226174050_d9d4a9f8b2`

Schema names derived from it:
- raw data: `raw_20260226174050_d9d4a9f8b2`
- analysis: `analysis_20260226174050_d9d4a9f8b2`

## Full reference

See [`docs/llm/README.md`](README.md) for complete command documentation with all options.
See [`docs/llm/manifest.json`](manifest.json) for the machine-readable command manifest.
