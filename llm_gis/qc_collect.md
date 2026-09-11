# qc_collect.py

## What it does

All the I/O behind QC: one normalized metrics dict out, whatever the source
(vector file, raster file/remote COG, PostGIS vector table, PostGIS raster
table). Vector aggregates run as SQL (DuckDB for files, PostgreSQL for
tables) rather than loading features into Python memory, so QC over a large
export costs a database scan, not a load. GDAL keeps authority over declared
geometry dimensionality (2D/3D/measured), which DuckDB's reader doesn't
reliably preserve.

## When you'd call it

Never directly — it's the measurement layer `qc.py` and `preview.py` both
call. You'd read this module when you need to know exactly what a QC
`metrics` block contains, or when adding a new source kind to QC.

## Key functions

- `file_vector_metrics(path, id_column)` — feature count, geometry-type
  histogram, empty/invalid counts, bbox, area or length stats (whichever the
  dominant geometry type implies), null counts per attribute, duplicate-ID
  count. CRS and declared dimensionality come from `ogrinfo` (`_ogr_facts`)
  for non-Parquet files, or from GeoParquet's own `geo` metadata for Parquet.
- `file_raster_metrics(source, exact_stats, bbox=None, bbox_crs="EPSG:4326")`
  — `gdalinfo -stats`/`-approx_stats` with `GDAL_PAM_ENABLED=NO` (so a
  `.aux.xml` write beside a read-only source can't fail). With a `bbox`,
  statistics run over a `raster.window_vrt` window rather than the whole
  raster — this is what makes a remote scene a viable QC source at all,
  since only the window's bytes cross the network.
- `file_metrics(path, id_column, exact_stats, bbox=None)` — dispatches to one
  of the above by extension; a remote URI with no recognizable suffix is
  treated as raster (this codebase has no remote vector reader yet, so
  guessing vector from an absent suffix would be worse than a clear
  raster-or-nothing rule).
- `table_metrics(schema, table, id_column)` — vector tables fully (via SQL
  aggregates in PostgreSQL/PostGIS), raster tables structurally only (pixel
  statistics over a tiled `raster_columns` entry are not implemented —
  `stats_mode: "none"`).

## How it fits the overall flow

The measurement half of QC, paired with `qc.py`'s judgment half. Also reused
directly by `preview.py` for its visual summary, and by `raster.py` indirectly
through the shared `window_vrt` helper it imports from `raster.py` for
bbox-scoped raster stats.
