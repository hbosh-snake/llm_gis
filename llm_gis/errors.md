# errors.py

## What it does

Defines `GisError`, the single exception type every module raises for a
caller-actionable failure, plus the fixed vocabulary of error codes
(`CRS_MISSING`, `COMMAND_FAILED`, `TABLE_NOT_FOUND`, `CATALOG_UNREACHABLE`,
etc.). Every `GisError` carries a code, a human message, a suggested next
action, and optional structured `details`.

## When you'd call it

You raise `GisError(CODE, message, suggested_action, details)` any time a
module hits a failure the caller should be told how to fix — a missing input
path, a CRS that can't be trusted, a table that doesn't exist, a subprocess
that exited non-zero. You don't call it to report a bug; that's an
unhandled Python exception, which `cli.py` catches separately as `UNEXPECTED`.

## Key classes

- `GisError(code, message, suggested_action, details=None)` — the exception.
  `.to_dict()` renders it as `{"status": "error", "code", "message",
  "suggested_action", "details"?}`, the shape `cli.py` prints to stderr before
  exiting 1.

## Error code vocabulary

`INPUT_NOT_FOUND`, `CRS_MISSING`, `CRS_SUSPICIOUS`, `UNSUPPORTED_FORMAT`,
`COMMAND_FAILED`, `PATH_OUTSIDE_ROOT`, `TABLE_NOT_FOUND`, `MISSING_ARGUMENT`,
`UNEXPECTED`, `CATALOG_UNREACHABLE`, `CATALOG_MALFORMED`, `ITEM_NOT_FOUND`,
`REMOTE_READ_FAILED`, `EMPTY_EXPORT_RESULT`. Some codes carry different force
in different contexts by design — e.g. `CRS_MISSING`/`CRS_SUSPICIOUS` are
advisory (exit 0, a QC warning) inside `bin/qc`, but fatal (exit 1) inside
`ingest-vector`/`ingest-raster`.

## How it fits the overall flow

Sits at the bottom of the dependency graph with `common.py` — no module
imports anything from it except the exception and the codes it needs.
`cli.py`'s `handle_errors` decorator is the single place that catches
`GisError` and renders it; every other module just raises and lets it
propagate.
