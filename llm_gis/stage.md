# stage.py

## What it does

Copies a source from the read-only `data/incoming/` into the writable
workspace (`data/work/staging/<ingest_id>/`) and hashes it, producing an
`ingest_id` other steps can reference. Unzips a `.zip` input automatically
(e.g. for shapefile sidecars). This is what makes `data/incoming/` safely
read-only-by-convention: nothing downstream ever writes back to it, because
everything works from the staged copy.

## When you'd call it

Via `bin/stage <path>` — an optional step before `ingest-vector`/
`ingest-raster` when a source needs a stable `ingest_id` established ahead of
time (e.g. multi-file inputs, or when `planner.py`'s generated plan calls for
it explicitly). Ingestion itself can also take a path directly and generate
its own `ingest_id`, so staging isn't always a required separate step.

## Key functions

- `stage_input(input_path, ingest_id=None)` — validates the input exists and
  is actually under `incoming_root()` (`ensure_child_path`, raising
  `PATH_OUTSIDE_ROOT` otherwise), hashes it, resolves or generates the
  `ingest_id`, copies file or directory into the staging directory, extracts
  a `.zip` in place if that's what was copied, and writes
  `data/work/reports/<ingest_id>.json`.

## How it fits the overall flow

The first step `planner.py` emits for any local source that needs to be
materialised into PostGIS (`stage` → `ingest-vector`/`ingest-raster`). Also
the step that gives a deterministic id (`planner._ingest_id`, derived from the
file's stem) so a printed plan's later steps stay pasteable without having
actually run staging yet.
