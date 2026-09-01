# Nepal Flood AOI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce a sourced, validated, dissolved AOI of Nepal municipalities shaded light blue in the supplied flood map and report its area in km².

**Architecture:** Acquire a documented Nepal local-unit boundary dataset, identify candidate municipalities independently from the map and dataset, then use the llm-gis ingest/SQL/export workflow to select and dissolve them. Preserve individual polygons and provenance alongside the final AOI.

**Tech Stack:** llm-gis CLI, GDAL/ogr2ogr, PostGIS 3.5, GeoPackage, GeoJSON, JSON

---

### Task 1: Establish the source dataset

**Files:**
- Create: `data/work/nepal-flood-aoi/source-notes.json`

1. Research authoritative or well-documented Nepal Admin-3/local-unit datasets.
2. Prefer an official Nepal or OCHA/HDX source; record version, date, license, and URL.
3. Download the chosen dataset into `data/incoming/` or stage it through the supported CLI.
4. Run `bin/inspect` and verify its CRS and layer inventory.

### Task 2: Identify affected municipalities

**Files:**
- Create: `data/work/nepal-flood-aoi/municipality-crosswalk.csv`

1. Transcribe all visible municipality labels in the light-blue region.
2. Inspect candidate local units by name, district, adjacency, and geometry.
3. Check for shaded but unlabeled polygons and document each inclusion/exclusion.
4. Record source identifiers, normalized names, districts, and confidence.

### Task 3: Ingest and select polygons

**Files:**
- Create: `data/work/<ingest_id>.sql`

1. Ingest the chosen boundary layer into a clearly named raw table.
2. Describe the raw table and use its exact lowercase columns.
3. Begin SQL with `CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;`.
4. Create a selected-municipalities table by stable identifiers where available.
5. Validate row count and municipality names against the crosswalk.

### Task 4: Dissolve and calculate area

**Files:**
- Modify: `data/work/<ingest_id>.sql`

1. Make geometries valid and dissolve the selection with `ST_UnaryUnion(ST_Collect(geom))`.
2. Calculate `area_km2` in a suitable equal-area CRS and cross-check geodesically.
3. Store source, selection count, and area attributes on the AOI record.
4. Describe both analysis tables and verify valid geometry.

### Task 5: Export and verify deliverables

**Files:**
- Create: `data/outgoing/2026-09-01_nepal-flood-aoi/nepal_flood_affected_municipalities.gpkg`
- Create: `data/outgoing/2026-09-01_nepal-flood-aoi/nepal_flood_affected_aoi.geojson`
- Create: `data/outgoing/2026-09-01_nepal-flood-aoi/manifest.json`

1. Export selected municipalities and dissolved AOI to GeoPackage.
2. Export the dissolved AOI to GeoJSON.
3. Inspect exported layers, feature counts, CRS, geometry validity, and area.
4. Write a provenance manifest and report any residual uncertainty.
