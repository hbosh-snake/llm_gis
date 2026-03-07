# Live Test Summary - 2026-02-26

## Scope

Validated the end-to-end workflow on a real dataset in `data/incoming`:
- input: `AOI_LAEA_3035.shp`
- flow: inspect -> ingest -> analyze (SQL) -> export

## Environment used

- Compose services: `db` + `agent`
- Database: Postgres 17 + PostGIS 3.5
- Tooling: GDAL 3.9.3, `psql` 16.11

## Commands executed (high level)

1. Inspect
   - `bin/inspect /data/incoming/AOI_LAEA_3035.shp`
2. Ingest (reproject for metric-safe analysis)
   - `bin/ingest-vector /data/incoming/AOI_LAEA_3035.shp --table aoi --dst-crs EPSG:3035`
3. Analysis SQL
   - `bin/run-sql /workspace/data/work/analysis_real.sql --ingest-id 20260226174050_d9d4a9f8b2`
4. Export
   - `bin/export /data/outgoing/aoi_exposure_20260226174050_d9d4a9f8b2.geojson --format geojson --table analysis_20260226174050_d9d4a9f8b2.aoi_exposure_ring`
   - `bin/export /data/outgoing/aoi_buffer_20260226174050_d9d4a9f8b2.gpkg --format gpkg --table analysis_20260226174050_d9d4a9f8b2.aoi_buffer_1km`

## Key inspection output

- Dataset kind: vector
- Layer: `AOI_LAEA_3035`
- Feature count: 1
- Geometry type: `PolygonZ`
- Detected CRS: `EPSG:4326`
- CRS status: `ok`

## Ingestion result

- `ingest_id`: `20260226174050_d9d4a9f8b2`
- Raw schema/table: `raw_20260226174050_d9d4a9f8b2.aoi`
- Chosen CRS: `EPSG:3035`
- Status: success

## Analysis tables created

- `analysis_20260226174050_d9d4a9f8b2.aoi_metrics`
- `analysis_20260226174050_d9d4a9f8b2.aoi_buffer_1km`
- `analysis_20260226174050_d9d4a9f8b2.aoi_exposure_ring`
- `analysis_20260226174050_d9d4a9f8b2.aoi_distance_probe`

## Analysis validation

- `aoi_metrics` rows: 1
- `aoi_exposure_ring` rows: 1
- `aoi_distance_probe.max_distance_m`: `5000.00`

## Output artifacts

- `data/outgoing/aoi_exposure_20260226174050_d9d4a9f8b2.geojson`
- `data/outgoing/aoi_buffer_20260226174050_d9d4a9f8b2.gpkg`

## Issues encountered and resolved during live run

1. `inspect` failed on GeoJSON extent shape
   - cause: parser assumed extent object; GDAL returned extent list
   - fix: `llm_gis/inspect.py` now supports both formats

2. False CRS suspicious flag for `EPSG:4326`
   - cause: substring matching treated `4326` as projected due to `326` match
   - fix: `llm_gis/common.py` now uses parsed EPSG codes

3. Potential schema creation race in vector ingest
   - cause: schema was created after `ogr2ogr` call
   - fix: `llm_gis/ingest_vector.py` now creates schema before load

4. Analysis SQL column mismatch
   - cause: referenced `"Name"` while ingested column is lowercase `name`
   - fix: updated SQL to use `name`

## Final status

Live test completed successfully with real data, including export artifacts and metric analysis outputs.
