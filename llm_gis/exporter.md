# exporter.py

## What it does

Writes a PostGIS table or an arbitrary SQL query out to a file — GeoPackage,
GeoJSON, or GeoParquet — via `ogr2ogr`, and by default runs a QC report over
what it just wrote before returning. This is the last step of nearly every
workflow: the point where analysis results leave the database and become a
deliverable in `data/outgoing/`.

## When you'd call it

Via `bin/export <path> --format gpkg|geojson|parquet --table <schema.table>`
or `--sql "SELECT ..."`. Always the final step after `run-sql` has produced
(or you're exporting straight from) a table.

## Key functions

- `export_result(output_path, output_format, table=None, sql_query=None, qc=True, compare_to=None, expect_non_empty=False)`
  — the whole operation. Requires exactly one of `table`/`sql_query`.
  Validates `output_format` against `gpkg`/`geojson`/`parquet`/`geoparquet`.
- `_to_geoparquet(source, destination)` — GeoParquet isn't a direct `ogr2ogr`
  output in this image (no Parquet driver in GDAL), so a Parquet export first
  writes a temporary GeoPackage, then converts it through DuckDB's own
  bundled GDAL (`COPY ... TO ... (FORMAT PARQUET)`), then deletes the
  temporary file.
- `_written_vector_summary(path)` — re-reads the file just written with
  `ogrinfo` to report the actual feature count and CRS that landed on disk,
  rather than trusting what was asked for.
- `_export_reference(table, compare_to)` — resolves what the QC
  disjointness check should compare the export against: `--compare-to` if
  given, else the source `--table` itself, else nothing. A `--sql` export has
  no inferable input, which is why `--compare-to` exists as a flag.

## QC integration

Unless `--no-qc`, every export attaches a `qc` block (see `qc.py`) built from
`QcContext(expect_non_empty, reference)`. If `--expect-non-empty` was passed
and the result actually came back empty, the export **fails** (raises
`GisError(EMPTY_EXPORT_RESULT, ...)`) rather than just warning — this is the
one place a QC finding becomes a hard failure instead of an advisory note in
the report.

## How it fits the overall flow

The terminal step of the standard PostGIS workflow (`inspect` → `ingest` →
`run-sql` → **`export`**). Also the terminal step of the DuckDB materialise
path in `planner.py`'s generated plans, and reachable directly from a
`postgis_table` source without any ingest step at all.
