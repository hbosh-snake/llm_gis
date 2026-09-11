# doctor.py

## What it does

The workspace smoke test: confirms GDAL and psql are on `PATH` and report a
version, confirms the database actually answers `SELECT 1`, and confirms the
expected data directories exist. There is no `tests/` directory in this
project — this is the closest thing to one, meant to be run right after
`docker compose up`.

## When you'd call it

Via `bin/doctor`, right after `docker compose up -d --build`, or any time
something is behaving strangely and you want to rule out "the environment
itself is broken" before debugging further.

## Key functions

- `doctor_report()` — gathers `ogrinfo --version` and `psql --version`
  output, attempts a trivial `psql -c "SELECT 1;"` (catching and reporting
  `GisError` rather than propagating it, since a broken DB shouldn't crash
  the diagnostic that's supposed to report it), checks
  `incoming_root()`/`/data/outgoing`/`work_root()` exist, and echoes the
  `PG*` environment variables actually in effect (not the password).

## How it fits the overall flow

Not part of any data pipeline — a standalone diagnostic. Everything else in
this package assumes the database is reachable and the workspace directories
exist; `doctor.py` is what confirms those assumptions before you rely on
them elsewhere.
