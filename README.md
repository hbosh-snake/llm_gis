# llm-gis

`llm-gis` is a small, headless GIS workspace you run with Docker.

You put geospatial files into `data/incoming/`, run a few commands, and get analysis results back in `data/outgoing/`.

This project is for:
- loading vector and raster data into PostGIS
- checking CRS information before import
- running repeatable spatial SQL
- exporting results as GeoPackage or GeoJSON

This project is not:
- a web map
- a desktop GIS
- a Jupyter notebook environment

## What You Need

Before you start, make sure you have:
- Docker
- Docker Compose

You do not need to install PostgreSQL, PostGIS, GDAL, or Python on your machine. Docker provides the working environment.

Run all commands in this README from the repo root directory unless noted otherwise.

## Project Folders

These are the only folders most people need to care about:

| Folder | Purpose |
|--------|---------|
| `data/incoming/` | Put raw input files here |
| `data/work/` | Temporary files, logs, and SQL working files |
| `data/outgoing/` | Exported results appear here, in dated subfolders |
| `data/archive/` | Processed source files are moved here after a workflow completes |

Examples of supported inputs:
- Shapefile
- GeoPackage
- GeoJSON
- GeoTIFF

If your data is a Shapefile, keep all of its sidecar files together, not just the `.shp` file. In practice, that usually means copying the full set of `.shp`, `.shx`, `.dbf`, and `.prj` files, or using a ZIP that contains them together.

## 5-Minute Setup

Clone the repo, start Docker, and verify the tools:

```bash
git clone <repo-url>
cd llm-gis
docker compose up -d --build
bin/doctor
```

What success looks like:
- Docker starts two services: `db` and `agent`
- `bin/doctor` returns JSON instead of an error

If `bin/doctor` fails, stop there and fix Docker before trying anything else.

You can also confirm both services are up with:

```bash
docker compose ps
```

## How The Workflow Works

The normal workflow is:

1. Put a dataset in `data/incoming/`
2. Inspect it to check CRS and basic metadata
3. Ingest it into PostGIS
4. Run a SQL analysis
5. Export the result to `data/outgoing/`

You do not prepare the database manually. The project creates the PostGIS extensions and metadata tables automatically on first startup.

## Quickstart: Vector Data

This is the simplest end-to-end example.

### 1. Copy a dataset into `data/incoming/`

Example:

```bash
cp /path/to/roads.gpkg data/incoming/
```

### 2. Inspect the dataset

```bash
bin/inspect data/incoming/roads.gpkg
```

Look for these fields in the JSON output:
- `dataset_kind`
- `detected_crs`
- `crs_status`
- `layers`

How to read `crs_status`:
- `ok`: safe to continue
- `missing`: the file has no usable CRS information
- `suspicious`: the CRS and the coordinate values do not match well enough to trust automatically

If the status is `missing` or `suspicious`, you must provide the correct CRS during ingest with `--src-crs EPSG:XXXX`.

### 3. Ingest the vector data into PostGIS

```bash
bin/ingest-vector data/incoming/roads.gpkg --table roads --dst-crs EPSG:3035
```

What this does:
- loads the file into PostGIS
- creates a schema named `raw_<ingest_id>`
- stores the table as `roads`
- reprojects to `EPSG:3035` on load

Why use `--dst-crs` here:
- distance, buffer, and area calculations should usually use a projected CRS, not latitude/longitude

Important:
- save the `ingest_id` from the JSON output
- you will use it in the next commands
- when you see `<ingest_id>` later in this README, replace it with that real value

If you already know the source CRS is wrong or missing, use:

```bash
bin/ingest-vector data/incoming/roads.gpkg --table roads --src-crs EPSG:4326 --dst-crs EPSG:3035
```

### 4. Check what was loaded

```bash
bin/describe-table raw_<ingest_id>.roads
```

Use this to confirm:
- the table exists
- the row count looks reasonable
- the column names are what you expect

## Run An Analysis

Create a SQL file in `data/work/`.

Example:

```sql
CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;

CREATE TABLE analysis_<ingest_id>.roads_buffer AS
SELECT
  fid,
  name,
  ST_Buffer(geom, 100) AS geom
FROM roads;
```

Save that as:

```text
data/work/analysis.sql
```

Replace `<ingest_id>` in the SQL with the actual value returned by `bin/ingest-vector`.

Then run it:

```bash
bin/run-sql data/work/analysis.sql --ingest-id <ingest_id>
```

What this does:
- connects to PostGIS
- sets the schema search path so `roads` resolves to the ingested table
- runs the SQL file
- stops on SQL errors

When you see angle brackets in examples, they are placeholders:
- replace `<ingest_id>` with the real ingest ID from the ingest step
- replace `EPSG:XXXX` with a real CRS code

Then verify the output table:

```bash
bin/describe-table analysis_<ingest_id>.roads_buffer
```

## Export The Result

Export to GeoPackage:

```bash
bin/export data/outgoing/roads_buffer.gpkg --format gpkg --table analysis_<ingest_id>.roads_buffer
```

Export to GeoJSON:

```bash
bin/export data/outgoing/roads_buffer.geojson --format geojson --table analysis_<ingest_id>.roads_buffer
```

Your output files will appear in `data/outgoing/`.

## Quickstart: Raster Data

Raster workflow is similar:

1. Put the raster in `data/incoming/`
2. Inspect it
3. Ingest it
4. Query it in PostGIS

Example:

```bash
bin/inspect data/incoming/elevation.tif
bin/ingest-raster data/incoming/elevation.tif --table elevation
```

If you need to reproject during raster ingest:

```bash
bin/ingest-raster data/incoming/elevation.tif --table elevation --dst-crs EPSG:3035
```

## Common Commands

| Command | Use it for |
|---------|------------|
| `bin/doctor` | Check that Docker, the database, and GIS tools are reachable |
| `bin/inspect <path>` | Read dataset metadata before import |
| `bin/ingest-vector <path> --table <name>` | Load vector data into PostGIS |
| `bin/ingest-raster <path> --table <name>` | Load raster data into PostGIS |
| `bin/describe-table <schema.table>` | Check what was loaded or created |
| `bin/run-sql <file> --ingest-id <id>` | Run a spatial SQL workflow |
| `bin/export <path> --format gpkg|geojson --table <schema.table>` | Write a result file |
| `bin/list-ingestions` | Review earlier ingests |

## What Gets Created Automatically

On first startup, the system creates:
- the PostgreSQL database container
- PostGIS extensions
- a metadata table for tracking ingests

You do not need to create schemas or extensions by hand before using the system.

## Troubleshooting

### `docker compose up` does not start cleanly

Check:
- Docker Desktop or Docker Engine is running
- no other local service is already using the required Docker resources

Then retry:

```bash
docker compose up -d --build
```

### `bin/doctor` fails

This usually means:
- Docker is not running
- the database container is not healthy yet
- the build did not complete cleanly

Check status:

```bash
docker compose ps
```

### `bin/inspect` says CRS is missing or suspicious

Do not ignore that.

Find the correct CRS for the source data, then ingest again with:

```bash
--src-crs EPSG:XXXX
```

### SQL runs but cannot find the table you expect

Check:
- you used the right `ingest_id`
- you created `analysis_<ingest_id>` in your SQL file
- you confirmed the raw table name with `bin/describe-table`

## Where To Find More Technical Detail

This README is for human operators.

If you are building agent workflows, extending commands, or working on the automation itself, use:
- [`AGENTS.md`](AGENTS.md)
- [`docs/llm/README.md`](docs/llm/README.md)
- [`docs/llm/QUICKSTART.md`](docs/llm/QUICKSTART.md)
