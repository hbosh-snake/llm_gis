# llm-gis

Headless geospatial analysis backend controlled through non-interactive CLI commands. Drop data in, run commands, get GeoPackage/GeoJSON out.

**What it is:** PostGIS + GDAL in Docker, driven by an AI coding agent or a human operator.
**What it is not:** A web GIS, map renderer, or desktop GIS environment.

---

## Prerequisites

- Docker and Docker Compose

## Setup

```bash
git clone <repo>
cd llm-gis
docker compose up -d --build
bin/doctor        # verify DB connectivity and tool versions
```

Data directories are created automatically on first run.

---

## Data paths

| Host path | Container path | Access | Purpose |
|-----------|---------------|--------|---------|
| `data/incoming/` | `/data/incoming` | read-only | Drop raw datasets here |
| `data/work/` | `/data/work` | read/write | Staging, logs, reports |
| `data/outgoing/` | `/data/outgoing` | read/write | Export outputs |
| `./` (repo root) | `/workspace` | read/write | SQL files, scripts |

---

## Commands

All `bin/*` scripts run inside the `agent` container. All output is JSON on stdout.

| Command | Description |
|---------|-------------|
| `bin/doctor` | Check DB connectivity and print GDAL/psql versions |
| `bin/inspect <path>` | Inspect a dataset; returns CRS, geometry type, extent, `crs_status` |
| `bin/stage <path>` | Hash and copy input to staging; returns an `ingest_id` |
| `bin/ingest-vector <path> --table <name>` | Load vector data into PostGIS via `ogr2ogr` |
| `bin/ingest-raster <path> --table <name>` | Load raster data into PostGIS via `raster2pgsql` |
| `bin/list-ingestions [--limit N]` | List all past ingestions from `meta.ingestions`, newest first |
| `bin/describe-table <schema.table>` | Show column names, types, and row count |
| `bin/run-sql <file> --ingest-id <id>` | Execute a SQL file with controlled `search_path` |
| `bin/export <path> --format gpkg\|geojson --table <schema.table>` | Export a table to file |

---

## Worked example

```bash
# 1. Inspect — check CRS before ingesting
bin/inspect data/incoming/roads.gpkg
# Check "crs_status" in output: "ok" -> proceed; "missing"/"suspicious" -> add --src-crs

# 2. Ingest — reproject to a metric CRS for spatial analysis
bin/ingest-vector data/incoming/roads.gpkg --table roads --dst-crs EPSG:3035
# Note the "ingest_id" in the output, e.g. "20260307120000_abc123def4"

# 3. Discover column names before writing SQL
bin/describe-table raw_20260307120000_abc123def4.roads

# 4. Write analysis SQL
cat > data/work/analysis.sql <<'SQL'
CREATE SCHEMA IF NOT EXISTS analysis_20260307120000_abc123def4;

CREATE TABLE analysis_20260307120000_abc123def4.roads_buffer AS
SELECT fid, name, ST_Buffer(geom, 100) AS geom
FROM roads;
SQL

# 5. Run the SQL
bin/run-sql data/work/analysis.sql --ingest-id 20260307120000_abc123def4

# 6. Verify the result was created
bin/describe-table analysis_20260307120000_abc123def4.roads_buffer

# 7. Export
bin/export data/outgoing/roads_buffer.gpkg \
  --format gpkg \
  --table analysis_20260307120000_abc123def4.roads_buffer
```

---

## CRS handling

`bin/inspect` returns a `crs_status` field:

- `"ok"` — proceed normally
- `"missing"` — no CRS found; add `--src-crs EPSG:XXXX` to the ingest command
- `"suspicious"` — CRS and extent are inconsistent; add `--src-crs EPSG:XXXX` to override

Use `--dst-crs` to reproject on load. For metric analyses (area, buffer, distance) always use a
projected CRS such as EPSG:3035 (Europe LAEA) or the appropriate regional UTM zone.

---

## Database schemas

| Schema | Contents |
|--------|---------|
| `meta.ingestions` | Per-ingest metadata — status, CRS decisions, paths, timestamps |
| `raw_<ingest_id>` | Source data loaded by ingest commands |
| `analysis_<ingest_id>` | Derived tables created by `run-sql` |

The database initializes itself on first boot: PostGIS extension, `meta` schema, `ingestions` table.

---

## Key conventions

- **Column names are always lowercase.** `ogr2ogr` lowercases all attribute names on load. `Name` → `name`.
- **Geometry column is `geom`, primary key is `fid`.** Always use these names in SQL.
- **The analysis schema is not auto-created.** Your SQL must begin with `CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;`.
- **Ingest ID format:** `YYYYMMDDHHMMSS_<first10ofSHA256>` — e.g. `20260226174050_d9d4a9f8b2`.

---

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PGHOST` | `db` | PostgreSQL host |
| `PGPORT` | `5432` | PostgreSQL port |
| `PGDATABASE` | `gis` | Database name |
| `PGUSER` | `gis` | Database user |
| `PGPASSWORD` | `gis` | Database password |
| `DATABASE_URL` | _(derived)_ | Takes precedence over individual vars if set |

---

## Agent documentation

- [`docs/llm/QUICKSTART.md`](docs/llm/QUICKSTART.md) — capabilities and constraints for an AI agent
- [`docs/llm/README.md`](docs/llm/README.md) — full command reference for an AI agent
- [`docs/llm/manifest.json`](docs/llm/manifest.json) — machine-readable command manifest
