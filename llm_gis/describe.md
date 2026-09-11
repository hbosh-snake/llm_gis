# describe.py

## What it does

Column names, PostgreSQL data types, nullability, defaults, and row count for
an already-ingested table. The PostGIS-table counterpart to `duck.describe`
(which does the same job for a Parquet/GeoParquet file).

## When you'd call it

Via `bin/describe-table <schema.table>` — right after `ingest-vector`/
`ingest-raster`, to get the exact (lowercased) column names before writing
SQL against the table, or after `run-sql` to verify a result table's shape.

## Key functions

- `describe_table(schema, table)` — queries `information_schema.columns` for
  the table's columns, then `COUNT(*)` for the row count. If no columns come
  back, distinguishes two cases: the table genuinely doesn't exist
  (`TABLE_NOT_FOUND`, suggesting `list-ingestions`) versus it exists but the
  connecting role can't see any columns (`TABLE_NOT_FOUND`, suggesting a
  `GRANT SELECT`).

## How it fits the overall flow

A verification step used twice in the standard workflow: once to confirm
what an ingest actually produced, and once after `run-sql` to confirm the
analysis output's shape before exporting it.
