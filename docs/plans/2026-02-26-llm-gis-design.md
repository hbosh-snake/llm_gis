# LLM-GIS Headless PostGIS Backend (Docker) Design

**Goal:** Provide a minimal, robust, reproducible, headless geospatial analysis backend that an LLM coding agent controls via filesystem + Python (uv) + SQL.

**Non-goals:** Web GIS, map rendering, GUI tooling, QGIS/PyQGIS, interactive workflows.

**Primary requirements (operational):**
- Drop raw datasets into `/data/incoming` (read-only to tools).
- Agent inspects datasets, confirms/overrides CRS, ingests to PostGIS (vector + raster).
- Agent runs spatial SQL analysis.
- Agent exports results to `/data/outgoing` as GeoPackage/GeoJSON.
- Deterministic across machines: pinned container images + pinned Python deps (uv lock).
- No manual DB preparation: DB initializes itself (schemas, extensions, metadata tables).

---

## Architecture

### Containers

1. **`db` (PostGIS)**
   - Stores all ingested vectors and rasters and all derived analysis outputs.
   - Initializes extensions and baseline schemas on first boot.
   - Persists across restarts using a named volume.

2. **`agent` (headless GIS toolbox + orchestration)**
   - Provides GDAL/PROJ/GEOS CLIs (`ogrinfo`, `ogr2ogr`, `gdalinfo`, `gdalwarp`) and PostGIS client tooling (`psql`, `raster2pgsql`).
   - Provides LLM-callable entrypoints (commands in `bin/`) that are non-interactive and write structured logs/reports to `/data/work`.
   - Uses `uv` (no `pip`, no `python` direct execution) for Python utilities.

### Shared volumes / paths

- `/data/incoming` (bind mount from `./data/incoming`, **read-only**) raw inputs
- `/data/outgoing` (bind mount from `./data/outgoing`, **rw**) exports
- `/data/work` (bind mount from `./data/work`, **rw**) staging, logs, reports, temp

Repo-local data is the default for portability; `data/**` is gitignored to prevent accidental commits.

### Network

- Compose internal network only by default.
- Optional host `5432:5432` port mapping can be enabled later if needed (not required for LLM workflows).

---

## Deterministic Base Images (Pinned)

1. **Database image:** `postgis/postgis:17-3.5`
   - Postgres 17 + PostGIS 3.5 (includes `postgis_raster` and raster loaders).
   - Tag is pinned; optionally pin image digests for maximum determinism.

2. **Agent image:** `ghcr.io/osgeo/gdal:ubuntu-small-3.9.3`
   - Provides a stable, prebuilt GDAL/PROJ/GEOS stack in-container.
   - Avoids host-to-host variability and GDAL ABI mismatch issues.

---

## System Packages (Agent)

Installed in the `agent` container on top of the GDAL base image:
- `postgresql-client` (for `psql`)
- `curl`, `ca-certificates` (install `uv`, fetch remote resources if needed)
- `jq` (parse `-json` outputs from GDAL tools in shell-based entrypoints)

Kept minimal; heavy computation should prefer PostGIS SQL.

---

## Python Tooling (uv-managed)

Python is used for orchestration and structured reporting (not heavy geoprocessing).

Required libraries (pinned via `uv.lock`):
- `typer` (stable CLI entrypoints)
- `pydantic` (structured config + report schemas)
- `psycopg[binary]` (DB connections when `psql` is insufficient)

Optional later only if needed:
- `pyproj` / `shapely` (prefer GDAL + SQL first)

---

## Database Initialization (No Manual Prep)

On first start (empty `pgdata` volume), the `db` container runs init scripts mounted into `/docker-entrypoint-initdb.d`:

- Create extensions automatically:
  - `postgis`
  - `postgis_raster`
  - `hstore`
  - `uuid-ossp`

- Create baseline schemas:
  - `meta` (ingestion bookkeeping and metadata)
  - `raw` (optional shared raw schema; primary mode is per-ingest schemas)
  - `analysis` (optional shared analysis schema; primary mode is per-ingest schemas)

- Create metadata tables (at minimum):
  - `meta.ingestions` for status, hashes, CRS decisions, timestamps, and pointers to logs/reports.

---

## Ingestion Strategy

### Vectors (Shapefile/GeoPackage/GeoJSON)

Default ingestion uses **GDAL (`ogr2ogr`) directly into PostGIS**, because:
- It is robust across formats.
- It avoids Python-level geometry conversions.
- It preserves attributes and supports reprojection at load time.

The agent uses a staging workflow:
1. Copy (or unpack) inputs from `/data/incoming` to `/data/work/staging/<ingest_id>/`.
2. Inspect with `ogrinfo -json` to detect:
   - layer names
   - geometry type(s)
   - CRS presence (authority if possible)
   - feature counts
3. If CRS is missing or suspicious, ingestion refuses unless a `--src-crs` override is supplied.
4. Load to PostGIS using `ogr2ogr` to a **per-ingest schema** and table name.
5. Post-load geometry normalization and validity enforcement happens in SQL:
   - `ST_IsValid` checks
   - `ST_MakeValid` fixes (tracked in metadata)
   - enforce 2D if required (`ST_Force2D`)
   - create spatial indexes after fixes

### Rasters

Default ingestion uses **PostGIS raster** tables:
1. Inspect with `gdalinfo -json`.
2. If CRS missing or suspicious, ingestion refuses unless `--src-crs` override is supplied.
3. Optional reprojection is performed safely with `gdalwarp` to the chosen target CRS.
4. Load using `raster2pgsql` into PostGIS raster tables in the per-ingest schema.

Zonal statistics and raster-vector operations prefer SQL (e.g., `ST_Intersects`, `ST_SummaryStatsAgg`, `ST_Clip`) after raster load.

---

## CRS Detection, Validation, and Reprojection Policy

### Detection
- Vectors: `ogrinfo -json` (layer `srs`), plus `gdalsrsinfo` when needed.
- Rasters: `gdalinfo -json` (dataset SRS and geotransform).

### Validation heuristics (non-exhaustive)
- Missing SRS: require explicit `--src-crs`.
- “Suspicious CRS” detection:
  - dataset claims geographic CRS but coordinates look like meters (very large absolute values)
  - dataset claims projected CRS but bounds resemble lon/lat ranges
  - bounds outside plausible ranges for the CRS’s units

### Reprojection (explicit and logged)
- Vectors: `ogr2ogr -s_srs <src> -t_srs <dst>`
- Rasters: `gdalwarp -s_srs <src> -t_srs <dst> ...`

All CRS decisions (detected, overridden, chosen) are recorded in `meta.ingestions` and written into `/data/work/reports/<ingest_id>.json`.

---

## Geometry Validity Enforcement

After vector load:
- Count invalid geometries (`NOT ST_IsValid(geom)`).
- Fix with `ST_MakeValid(geom)` into-place or into a normalized table.
- Record counts (invalid before, fixed, still invalid) in metadata.
- Create spatial index only after normalization.

For downstream analysis:
- Prefer running on normalized/valid tables to prevent analysis failures.

---

## Schema and Naming Conventions

### Per-ingest schemas (default)
- `raw_<ingest_id>`: tables representing ingested datasets (vector + raster).
- `analysis_<ingest_id>`: derived results (tables/views) produced by analysis workflows.

`<ingest_id>` is a stable identifier derived from input content hash plus timestamp to allow idempotency checks and safe retries.

### Table naming
- Sanitized names, deterministic mapping:
  - dataset stem + optional layer name suffix
  - strict character whitelist: `[a-z0-9_]+`

### Convenience pointers
- Optionally maintain `raw_latest` and `analysis_latest` schemas containing views pointing at the most recent successful ingestion.

---

## Safe Query Execution Model (LLM-driven)

Queries run through a controlled entrypoint:
- Sets `search_path` explicitly (`analysis_<id>, raw_<id>, public`) to reduce accidental cross-ingest writes.
- Uses `ON_ERROR_STOP=1` and a configured `statement_timeout`.
- Logs:
  - SQL file
  - `psql` output
  - summary JSON (rowcounts, created objects)

If needed later, introduce a limited DB role that can only create objects in `analysis_<id>` and read `raw_<id>`.

---

## Export Model

Exports are performed by `ogr2ogr` (PostGIS -> file):
- GeoPackage for multi-layer results
- GeoJSON for lightweight interchange

Exports go only to `/data/outgoing`, with an export report written to `/data/work/reports/<export_id>.json`.

---

## Temp Files, Logs, and Reports

- All temporary files live under `/data/work/tmp`.
- Logs under `/data/work/logs/<ingest_id>/`.
- Structured reports under `/data/work/reports/`.

---

## Failure Recovery

- Each ingestion operates in an isolated schema; failures do not corrupt previous ingests.
- Failed ingests remain inspectable; cleanup is explicit (`bin/cleanup --failed`).
- Idempotency:
  - input content hash is recorded
  - re-ingesting identical inputs can be detected and skipped or versioned

---

## LLM Discoverability Metadata

Expose a small, machine-readable manifest to the agent:
- `docs/llm/manifest.json`
  - paths (`/data/incoming`, `/data/outgoing`, `/data/work`)
  - command catalog (`bin/*`) with arguments and examples
  - database connection env vars
  - schema conventions and safety rules

Plus a human-readable operator doc:
- `docs/llm/README.md`

