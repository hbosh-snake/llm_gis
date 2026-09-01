# Nepal Flood-Affected Municipalities AOI — Job Checkpoint

Status: **complete and reproducible**  
Saved: 2026-09-01  
Ingest ID: `20260901101020_f5d06bbc2d`

## Result

- AOI definition: the 17 municipalities shaded light blue in the supplied map.
- Dissolved AOI area: **3,123.415498 km²** using equal-area EPSG:6933.
- Geodesic cross-check: **3,123.415497 km²**.
- Stored analysis geometry: EPSG:32645.
- Dissolved geometry: one valid, nonempty MultiPolygon.

## Sources

- User image: `data/incoming/image (2).png`
- Boundary archive: `data/incoming/npl_admin_boundaries.geojson.zip`
- Extracted source layer: `data/incoming/npl_admin3.geojson`
- Boundary source: OCHA/HDX Nepal COD-AB v02, valid 2024-03-14.
- Dataset page: <https://data.humdata.org/dataset/cod-ab-npl>
- License: CC BY 3.0 IGO.

The source files remain in `data/incoming/`; they have not been archived.

## Database State

- Raw table: `raw_20260901101020_f5d06bbc2d.nepal_admin3`
- Selected municipalities: `analysis_20260901101020_f5d06bbc2d.selected_municipalities`
- Dissolved AOI: `analysis_20260901101020_f5d06bbc2d.flood_affected_aoi`
- Reproducible SQL: `data/work/20260901101020_f5d06bbc2d.sql`
- SQL log: `data/work/logs/20260901101020_f5d06bbc2d/run-sql.log`
- Crosswalk: `data/work/nepal-flood-aoi/municipality-crosswalk.csv`
- Source notes: `data/work/nepal-flood-aoi/source-notes.json`
- Delivery manifest: `data/work/nepal-flood-aoi/manifest.json`

## Selected Admin-3 P-codes

`NP0329401`, `NP0329402`, `NP0329403`, `NP0329404`, `NP0328402`,
`NP0328301`, `NP0328403`, `NP0328302`, `NP0330407`, `NP0330410`,
`NP0330409`, `NP0330408`, `NP0436408`, `NP0436409`, `NP0440405`,
`NP0440406`, `NP0335401`.

## Deliverables

All deliverables are under `data/outgoing/2026-09-01_nepal-flood-aoi/`:

- `nepal_flood_affected_aoi.kmz` — recommended Google Earth delivery.
- `nepal_flood_affected_aoi.kml` — uncompressed Google Earth delivery.
- `nepal_flood_affected_aoi.gpkg` — dissolved projected AOI.
- `nepal_flood_affected_aoi.geojson` — dissolved WGS84 AOI.
- `selected_municipalities.gpkg` — 17 individual municipalities.
- `municipality-crosswalk.csv` — image-label/P-code audit trail.
- `manifest.json` — provenance, methods, counts, areas, and hashes.

## Resume Existing Job

Start Docker and verify the existing database state:

```bash
docker compose up -d
bin/doctor
bin/describe-table analysis_20260901101020_f5d06bbc2d.selected_municipalities
bin/describe-table analysis_20260901101020_f5d06bbc2d.flood_affected_aoi
```

To rerun the analysis from the existing raw ingestion:

```bash
bin/run-sql /data/work/20260901101020_f5d06bbc2d.sql \
  --ingest-id 20260901101020_f5d06bbc2d
```

To regenerate the standard AOI exports:

```bash
bin/export /data/outgoing/2026-09-01_nepal-flood-aoi/nepal_flood_affected_aoi.gpkg \
  --format gpkg \
  --table analysis_20260901101020_f5d06bbc2d.flood_affected_aoi

bin/export /data/outgoing/2026-09-01_nepal-flood-aoi/selected_municipalities.gpkg \
  --format gpkg \
  --table analysis_20260901101020_f5d06bbc2d.selected_municipalities
```

Existing exports must first be moved aside because `bin/export` does not overwrite them.

## Restart From Source

If the database volume is unavailable, inspect and ingest the extracted Admin-3 source again:

```bash
bin/inspect /data/incoming/npl_admin3.geojson
bin/ingest-vector /data/incoming/npl_admin3.geojson \
  --table nepal_admin3 \
  --dst-crs EPSG:32645
```

The new ingest receives a new timestamped ID. Copy the saved SQL, replace the old ingest ID in schema/table names, then run it with the new ID. Verify 17 selected rows and one dissolved AOI before exporting.

## Notes for the Next Agent

- The light-blue municipalities—not the dark-blue river/flood footprint—define the AOI.
- Do not infer selection from other PostGIS state; use the saved source and P-code crosswalk.
- GeoJSON must be EPSG:4326; projected GeoPackages remain EPSG:32645.
- Area is authoritative from EPSG:6933 and must remain approximately 3,123.415498 km².
- The KML/KMZ feature contains the area and source metadata.
