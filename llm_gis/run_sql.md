# run_sql.py

## What it does

Executes an analyst-supplied `.sql` file against the PostGIS workspace, with
a controlled preamble that sets a statement timeout and a `search_path`
scoped to the ingest's own raw and analysis schemas — so the SQL can
reference raw tables without schema-qualifying them, and any `CREATE TABLE`
lands in the analysis schema by default.

## When you'd call it

Via `bin/run-sql <file> --ingest-id <id> [--statement-timeout 5min]` — the
step between ingestion and export, once you've written analysis SQL to
`data/work/<ingest_id>.sql`. **The SQL file must begin with**
`CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;` per the workflow
convention (this module also injects it into the preamble, but the analysis
schema is not auto-created for the file's own reference before that point).

## Key functions

- `run_sql_file(sql_path, ingest_id, statement_timeout="5min")` — reads the
  file, prepends:
  ```sql
  SET statement_timeout = '5min';
  CREATE SCHEMA IF NOT EXISTS analysis_<id>;
  SET search_path TO analysis_<id>, raw_<id>, public;
  ```
  runs the combined text through `psql -f -` (piped via stdin, not a
  temp file), logs the full psql output to
  `data/work/logs/<ingest_id>/run-sql.log`, and reports row counts for every
  table that appeared in the analysis schema during this run (diffed
  before/after via `_table_names`) — not every table in the schema, just the
  ones this invocation added.

## How it fits the overall flow

Step 5 of the standard workflow (`inspect` → `ingest` → `describe-table` →
**`run-sql`** → `describe-table` → `export`). The only module in this
package that runs caller-supplied raw SQL rather than building SQL from
flags — `query.py` and `raster.py`'s zonal stats are the "safe", flag-driven
alternative for filtering; `run_sql.py` is the explicitly privileged escape
hatch for real analysis.
