# llm-gis — Agent Quick Start

Headless geospatial analysis backend controlled through non-interactive CLI commands. PostGIS + GDAL in Docker, driven by an AI coding agent or human operator. Every command returns JSON on stdout.

**Not** a web GIS, map renderer, or desktop GIS.

---

## Architecture

Three layers:
1. **`bin/` shell wrappers** — the only interface. Each calls `docker compose run --rm agent uv run llm-gis <cmd> "$@"`.
2. **`llm_gis/cli.py`** — Typer app with all subcommands, prints JSON output.
3. **`llm_gis/*.py` modules** — one file per capability; share `llm_gis/common.py` for DB, hashing, subprocess, CRS validation.

## Tech Stack

- Python 3.12 + `uv`, Typer, psycopg 3, Pydantic 2, GeoPandas
- PostgreSQL 17 + PostGIS 3.5 + postgis_raster
- GDAL 3.9.3 (ogr2ogr, ogrinfo, gdalinfo, gdalwarp, raster2pgsql)
- Docker Compose — services: `db` (PostGIS) and `agent` (GDAL + Python)

## Commands

```bash
bin/doctor
bin/inspect <path>
bin/stage <path> [--ingest-id <id>]
bin/ingest-vector <path> --table <name> [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]
bin/ingest-raster  <path> --table <name> [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]
bin/list-ingestions [--limit N]
bin/describe-table <schema.table>
bin/run-sql <file> --ingest-id <id> [--statement-timeout 5min]
bin/export <path> --format gpkg|geojson --table <schema.table>
bin/export <path> --format gpkg|geojson --sql "SELECT ..."
```

## Source-of-Truth Checkpoint

- If the user references a file in `data/incoming/`, treat that file as the source of truth.
- Do not analyze an existing PostGIS table when the request clearly points to an incoming file.
- If the incoming archive contains multiple polygon layers and the request does not name one, inspect first and identify the candidate layers before choosing a target.
- If more than one layer could satisfy the request, ask which layer to use instead of guessing.
- Before writing analysis SQL, state the source path, the chosen layer or layers, and the expected output table.

## Standard Workflow

```
1. bin/inspect /data/incoming/<file>
   → check crs_status: "ok" / "missing" / "suspicious"

2. bin/ingest-vector /data/incoming/<file> --table <name> --dst-crs EPSG:3035
   → note "ingest_id" from output (format: YYYYMMDDHHMMSS_<first10sha256>)

3. bin/describe-table raw_<ingest_id>.<name>
   → read exact column names before writing SQL

4. Write SQL to /data/work/<ingest_id>.sql
   → MUST start with: CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;

5. bin/run-sql /data/work/<ingest_id>.sql --ingest-id <ingest_id>

6. bin/describe-table analysis_<ingest_id>.<result_table>
   → verify rows created

7. bin/export /data/outgoing/result.gpkg --format gpkg --table analysis_<ingest_id>.<result_table>
```

## Ambiguity Rule

- For requests like "for each polygon" or "top N polygons", do not infer the layer from prior PostGIS state.
- Prefer the incoming file, then the specific layer name, then the analysis table derived from that ingest.
- If any step depends on a choice the user did not specify, stop and ask for that choice.

## Hard Constraints

- **Column names are always lowercase.** `ogr2ogr` lowercases on load. Never quote mixed-case names in SQL.
- **Geometry column is `geom`, primary key is `fid`.** These are set at ingest. Use them in all SQL.
- **Analysis schema is NOT auto-created.** Your SQL must begin with `CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;`
- **CRS must be resolved before ingesting.** If `crs_status` is `missing` or `suspicious`, add `--src-crs EPSG:XXXX`.
- **Use a projected CRS for metric work.** Buffer/area/distance need metric CRS. Use EPSG:3035 (Europe) or appropriate UTM.

## Data Paths

| Host path | Container path | Access |
|-----------|---------------|--------|
| `data/incoming/` | `/data/incoming` | read-only during processing |
| `data/work/` | `/data/work` | read/write |
| `data/outgoing/` | `/data/outgoing` | read/write |
| `data/archive/` | — | post-workflow archive for processed source files |
| `./` (repo root) | `/workspace` | read/write |

**Post-workflow:** Results go in `data/outgoing/YYYY-MM-DD_<project-name>/`. After confirmation, source files move from `data/incoming/` to `data/archive/`.

## Database

- Default: `gis/gis@db:5432/gis` — no `.env` needed
- `DATABASE_URL` overrides individual `PG*` vars if set
- Auto-initialized on first boot (PostGIS extensions, meta schema, ingestions table)
- DB schemas: `meta.ingestions` (history), `raw_<id>` (source data), `analysis_<id>` (derived tables)

## Key Source Files

| File | Role |
|------|------|
| `llm_gis/cli.py` | All Typer subcommand definitions |
| `llm_gis/common.py` | `pg_dsn`, `sha256_for_path`, `run_subprocess`, `sanitize_identifier` |
| `llm_gis/inspect.py` | CRS status logic, ogrinfo/gdalinfo parsing |
| `llm_gis/ingest_vector.py` | ogr2ogr + ST_MakeValid + ST_Force2D + GIST index |
| `llm_gis/ingest_raster.py` | gdalwarp (optional) + raster2pgsql pipeline |
| `llm_gis/run_sql.py` | psql execution with search_path preamble |
| `llm_gis/exporter.py` | ogr2ogr export to GeoPackage/GeoJSON |
| `docker-compose.yml` | Service definitions, volumes, env vars |

## What `run-sql` Does Behind the Scenes

Prepends before your SQL:
```sql
SET statement_timeout = '5min';
SET search_path TO analysis_<id>, raw_<id>, public;
```
Your SQL can reference raw tables without schema qualification. Logs go to `/data/work/logs/<id>/run-sql.log`.

## Setup from Scratch

```bash
docker compose up -d --build
bin/doctor   # verify DB connectivity and tool versions
```

## No Tests

No `tests/` directory. `bin/doctor` is the smoke test. Results in `docs/reports/`.

## Full Reference

- `docs/llm/QUICKSTART.md` — hard constraints and workflow details
- `docs/llm/README.md` — complete command documentation with all options
- `docs/llm/manifest.json` — machine-readable command manifest
