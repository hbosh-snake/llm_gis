# planner.py

## What it does

Decides which engine — DuckDB, PostGIS, or GDAL — should run a job, states
the reasoning, and renders the exact serial `bin/*` command list that would
carry it out. **Executes nothing.** Pure and DB-free by design: it classifies
a URI purely from its suffix and scheme, so it can answer at discovery time,
before anything has actually been opened.

The single axis it routes on is whether the result must outlive the command
that produced it (`--materialise`). Dataset size never branches a routing
rule.

## When you'd call it

Via `bin/plan <query|analyse|export> <source> [--bbox] [--where] [--materialise] [--engine]`
— when you want to know what would happen before committing to it, or when
you're unsure which engine is right for a source you just discovered via
`catalog-search`.

## Key functions and classes

- `classify(uri)` → `Source(uri, format, locality, readers)` — format from
  suffix (`parquet`/`vector_file`/`postgis_table`/`raster`), locality
  (`local`/`remote`) from scheme, `readers` from the module-level `READERS`
  table.
- `readers(format_)` — **the single authoritative format-to-engine table** in
  this workspace (`catalog.readable_by` is a narrower projection of it, kept
  for `duck-query` compatibility).
- `route(operation, source, materialise=False, engine=None)` → `Route` — the
  routing decision for `query`/`analyse`/`export`, with `_query_route`,
  `_analyse_route`, `_export_route` as the per-operation rule tables. An
  explicit `--engine` override is honoured if the source can support it
  (`_refuse_override` raises otherwise), and the route records `overridden`
  and a `fallback` so the caller sees what was passed up.
- `steps(operation, source, decided, ...)` → `list[Step]` — turns a `Route`
  into the actual `bin/*` invocations (`stage` → `ingest-vector`/
  `ingest-raster` → `run-sql` → `export`, or a single `duck-query`/
  `raster-window` call for an in-place read).
- `plan(operation, uri, ...)` — the full answer: route + reason + fallback +
  warnings + steps, as one dict (what `bin/plan` prints).
- `_asset_warnings(operation, asset)` — attaches warnings (e.g.
  `CRS_SUSPICIOUS`, `EMPTY_SOURCE`) when a caller hands in an already-measured
  `Asset` (from `inspect`/`duck-describe`/`catalog-assets`) — a URI alone
  can't support these, since they need a measurement, not just a suffix.

## Known blocked routes

Some combinations are refused rather than routed: Parquet has no
`--materialise` path into a GDAL-readable file today (no Parquet driver in
this GDAL build), and pixel statistics over a *tiled PostGIS raster table*
aren't implemented (use `bin/raster-window --zones` instead, which needs no
database). These surface as `blocked_by` in the plan output with a
`NO_CONVERSION_PATH` code and a specific suggested action.

## How it fits the overall flow

Sits above every execution module without depending on their logic — it only
imports `errors.py`. `catalog.readers_for` calls `planner.classify` to report
what could open a STAC asset's href. Every `bin/*` step name it emits
(`stage`, `ingest-vector`, `run-sql`, `export`, `duck-query`,
`raster-window`) names a real command elsewhere in this package; `plan` is
purely descriptive of the workflow those modules actually carry out.
