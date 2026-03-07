# llm-gis

Headless geospatial ingestion and analysis backend for an LLM coding agent.

## Purpose

This repository provides a deterministic, containerized GIS backend for:
- vector and raster ingestion
- CRS inspection and validation
- PostGIS-native spatial SQL analysis
- GeoPackage/GeoJSON export

No GUI tooling is required.

## Architecture

- `db`: `postgis/postgis:17-3.5`
- `agent`: `ghcr.io/osgeo/gdal:ubuntu-small-3.9.3` + `uv` + CLI wrappers
- Repo-local mounted data paths:
  - incoming (read-only): `data/incoming` -> `/data/incoming`
  - outgoing (read/write): `data/outgoing` -> `/data/outgoing`
  - work (read/write): `data/work` -> `/data/work`

## Prerequisites

- Docker with Compose
- `uv` installed locally (for non-container local command checks only)

## Setup

1. Start services:

```bash
docker compose up -d db
docker compose build agent
```

2. Validate environment:

```bash
bin/doctor
```

Expected: `database_ok: true` and tool versions printed.

## Standard workflow

1. Drop data into `data/incoming`.
2. Inspect dataset:

```bash
bin/inspect /data/incoming/<dataset>
```

3. Ingest dataset:

```bash
# vector
bin/ingest-vector /data/incoming/<dataset> --table <table_name> [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]

# raster
bin/ingest-raster /data/incoming/<dataset> --table <table_name> [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]
```

4. Run analysis SQL:

```bash
bin/run-sql /workspace/<path-to-sql-file> --ingest-id <ingest_id>
```

5. Export results:

```bash
bin/export /data/outgoing/<result>.gpkg --format gpkg --table analysis_<ingest_id>.<table>
bin/export /data/outgoing/<result>.geojson --format geojson --table analysis_<ingest_id>.<table>
```

## Data and schema conventions

- Metadata table: `meta.ingestions`
- Raw ingest schema: `raw_<ingest_id>`
- Analysis schema: `analysis_<ingest_id>`
- Logs: `data/work/logs/<ingest_id>/`
- Reports: `data/work/reports/<ingest_id>.json`

## Safety rules

- Inputs are read from `/data/incoming` (mounted read-only).
- If CRS is missing or suspicious, pass `--src-crs` explicitly.
- Use projected CRS (for example `EPSG:3035`) for metric analyses (area, buffer, distance).
- Execute analysis through `bin/run-sql` for controlled `search_path` and failure behavior.

## Key entrypoints

- `bin/stage`
- `bin/inspect`
- `bin/ingest-vector`
- `bin/ingest-raster`
- `bin/run-sql`
- `bin/export`
- `bin/doctor`
- `scripts/smoke.sh`

## Discoverability docs for agents

- `docs/llm/manifest.json`
- `docs/llm/README.md`

## Reference plan docs

- `docs/plans/2026-02-26-llm-gis-design.md`
- `docs/plans/2026-02-26-llm-gis-implementation-plan.md`
# llm_gis
