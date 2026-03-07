# LLM GIS Backend — Operator Notes

## Canonical paths

| Path | Access | Purpose |
|------|--------|---------|
| `/data/incoming` | read-only | Drop raw datasets here |
| `/data/work` | read/write | Staging, logs (`logs/<ingest_id>/`), reports (`reports/<ingest_id>.json`) |
| `/data/outgoing` | read/write | Export outputs |
| `/workspace` | read/write | Repo root (SQL files, scripts) |

## Commands

All `bin/*` scripts are non-interactive wrappers: `docker compose run --rm agent uv run llm-gis <cmd> ...`. All output is JSON on stdout.

### `bin/doctor`
Checks DB connectivity and tool versions.
```
bin/doctor
```

### `bin/stage`
Hashes and stages input into `/data/work/staging/<ingest_id>/`. Emits a report to `/data/work/reports/<ingest_id>.json`.
```
bin/stage <input_path> [--ingest-id <id>]
```

### `bin/inspect`
Runs `ogrinfo`/`gdalinfo` and returns metadata with `crs_status` (`ok`, `suspicious`, or `missing`).
```
bin/inspect <input_path> [--ingest-id <id>]
```

### `bin/ingest-vector`
Loads a vector dataset into `raw_<ingest_id>.<table>` via `ogr2ogr`. Runs `ST_MakeValid` and `ST_Force2D`. Upserts `meta.ingestions`.
```
bin/ingest-vector <input_path> --table <name> \
  [--ingest-id <id>] [--schema <schema>] \
  [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]
```
- `--src-crs`: required when `crs_status` is `missing` or `suspicious`
- `--dst-crs`: reprojects on load (recommended for metric analysis)

### `bin/ingest-raster`
Reprojects with `gdalwarp` (if `--dst-crs`), then loads with `raster2pgsql` into `raw_<ingest_id>.<table>`.
```
bin/ingest-raster <input_path> --table <name> \
  [--ingest-id <id>] [--schema <schema>] \
  [--src-crs EPSG:XXXX] [--dst-crs EPSG:YYYY]
```

### `bin/run-sql`
Executes a `.sql` file with `ON_ERROR_STOP=1` and `search_path = analysis_<ingest_id>, raw_<ingest_id>, public`.
```
bin/run-sql <sql_file> --ingest-id <id> [--statement-timeout 5min]
```
- SQL file must be under `/workspace` or `/data/work`.

### `bin/export`
Exports a PostGIS table or query to GeoPackage or GeoJSON via `ogr2ogr`.
```
bin/export <output_path> --format gpkg|geojson \
  [--table analysis_<ingest_id>.<table>] \
  [--sql "SELECT ..."]
```
- Either `--table` or `--sql` is required.
- Output path must be under `/data/outgoing`.

### `bin/list-ingestions`
Query `meta.ingestions` and return all ingests sorted newest-first.
```
bin/list-ingestions [--limit 50]
```
Output fields: `ingest_id`, `input_path`, `detected_crs`, `chosen_crs`, `status`, `created_at`, `updated_at`.

### `bin/describe-table`
Return column names, types, and row count for any PostGIS table.
```
bin/describe-table <schema.table>
```
Examples: `bin/describe-table meta.ingestions`, `bin/describe-table raw_<ingest_id>.roads`.
Output fields: `schema`, `table`, `columns` (list of `{column_name, data_type, is_nullable}`), `row_count`.

## Known behaviors

### Column names are always lowercase
`ogr2ogr` lowercases all attribute column names when loading to PostgreSQL. A source field `Name` becomes `name`, `OBJECTID` becomes `objectid`. Always use lowercase in SQL.

### Geometry column is always `geom`, FID is `fid`
Every vector table loaded by `ingest-vector` uses `-lco GEOMETRY_NAME=geom -lco FID=fid`. Reference geometry as `geom` in all SQL.

### `analysis_<ingest_id>` schema must be created by your SQL
`run-sql` sets `search_path` but does NOT create the analysis schema. Your SQL file must start with:
```sql
CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;
```
Replace `<ingest_id>` with the literal value returned by `ingest-vector`.

## Database

Default connection (overridable via env):

| Env var | Default |
|---------|---------|
| `DATABASE_URL` | (takes precedence if set) |
| `PGHOST` | `db` |
| `PGPORT` | `5432` |
| `PGDATABASE` | `gis` |
| `PGUSER` | `gis` |
| `PGPASSWORD` | `gis` |

## Schema conventions

| Schema | Contents |
|--------|---------|
| `meta.ingestions` | Per-ingest metadata: status, hashes, CRS decisions, paths |
| `raw_<ingest_id>` | Source data loaded by ingest commands |
| `analysis_<ingest_id>` | Derived tables created by `run-sql` |

## Standard workflow

A complete workflow from raw data to export. Each command outputs JSON; the key fields needed for the next step are shown explicitly.

**1. Inspect the dataset**
```
bin/inspect /data/incoming/mydata.gpkg
```
Check `crs_status` in the output:
- `"ok"` → proceed
- `"missing"` or `"suspicious"` → add `--src-crs EPSG:XXXX` to the ingest command

**2. Ingest**
```
bin/ingest-vector /data/incoming/mydata.gpkg --table roads --dst-crs EPSG:3035
```
From the JSON output, note the `ingest_id` value (e.g. `"20260307120000_abc123def4"`). You will use this in every subsequent step.

The raw table is now at `raw_<ingest_id>.roads`. All column names are lowercase.

**3. Describe the raw table (discover column names)**
```
bin/describe-table raw_<ingest_id>.roads
```
Use the returned `columns` list to write correct SQL.

**4. Write and run analysis SQL**

Create `/workspace/data/work/analysis_<ingest_id>.sql`:
```sql
CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;

CREATE TABLE analysis_<ingest_id>.roads_buffer AS
SELECT fid, name, ST_Buffer(geom, 100) AS geom
FROM roads;
```

Then run it:
```
bin/run-sql /workspace/data/work/analysis_<ingest_id>.sql --ingest-id <ingest_id>
```

**5. Describe the result (verify it was created)**
```
bin/describe-table analysis_<ingest_id>.roads_buffer
```

**6. Export**
```
bin/export /data/outgoing/roads_buffer.gpkg --format gpkg --table analysis_<ingest_id>.roads_buffer
bin/export /data/outgoing/roads_buffer.geojson --format geojson --table analysis_<ingest_id>.roads_buffer
```

**7. List all ingestions (to review or resume work)**
```
bin/list-ingestions
```

## CRS policy

- Ingestion fails if `crs_status` is `missing` or `suspicious` unless `--src-crs` is provided.
- Use a projected CRS (e.g. `EPSG:3035`) for metric analyses (area, buffer, distance).

## Ingest ID format

`YYYYMMDDHHMMSS_<first10ofSHA256>` — e.g. `20260226174050_d9d4a9f8b2`
