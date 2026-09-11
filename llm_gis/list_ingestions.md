# list_ingestions.py

## What it does

Lists recent rows from `meta.ingestions`, the append/upsert log every
ingestion (`ingest_vector.py`, `ingest_raster.py`) writes to. Answers "what
has already been loaded into this workspace, and under what ingest ID?"

## When you'd call it

Via `bin/list-ingestions [--limit N]` — to recall an `ingest_id` from an
earlier session, to check whether a source has already been ingested before
re-running an ingest, or as the suggested next step when `describe_table`
can't find a table.

## Key functions

- `list_ingestions(limit=50)` — `SELECT ingest_id, input_path, detected_crs,
  chosen_crs, status, created_at, updated_at FROM meta.ingestions ORDER BY
  created_at DESC LIMIT %s`, with datetime columns rendered as ISO 8601
  strings for JSON output.

## How it fits the overall flow

A read-only lookup over the side effect `ingest_vector.py`/`ingest_raster.py`
produce in `meta.ingestions`. Doesn't participate in any pipeline itself —
it's the audit trail for the ones that do.
