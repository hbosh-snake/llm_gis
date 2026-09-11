# qc.py

## What it does

The five deterministic quality checks and the report envelope. Everything
here is pure: given a metrics dict (collected by `qc_collect.py`) and a
`QcContext` (what the caller declared about the job), it judges and returns a
report — it never opens a file or a database connection itself. A check
result is `pass`, `warn`, or `not_evaluated`; an unsupplied comparison is
`not_evaluated`, not a silent pass.

## When you'd call it

Via `bin/qc <path-or-table> [--expect-non-empty] [--metric-op] [--compare-to <ref>] [--id-column <c>] [--exact-stats]`
— run explicitly to check a dataset, or implicitly every time `bin/export`
runs (unless `--no-qc`).

## Key classes and functions

- `QcContext(expect_non_empty, metric_op, id_column, reference)` — what the
  caller declared. Each field gates exactly one check; without it that check
  reports `not_evaluated`.
- `build_report(source, metrics, context)` — runs all five `CHECKS`, collects
  the ones that `warn` into a `warnings` list, sets `qc_status` to
  `"warning"` if any exist else `"ok"`.
- `qc_report(ref, context, exact_stats=False, bbox=None)` — the entry point:
  resolves `ref` to a file or `schema.table` (`resolve_source`), collects
  metrics via `qc_collect`, and builds the report.
- `reference_for(ref)` — collects just the CRS/bbox of a comparison source,
  for `--compare-to`.

## The five checks

| Function | Code | Fires when |
|---|---|---|
| `check_crs_missing` | `CRS_MISSING` | No CRS detected |
| `check_crs_suspicious` | `CRS_SUSPICIOUS` | CRS doesn't match the extent (lon/lat in a projected CRS, or the reverse) |
| `check_geographic_crs_for_metric_operation` | `GEOGRAPHIC_CRS_FOR_METRIC_OPERATION` | `--metric-op` declared and the CRS is geographic (degrees, not metres) |
| `check_empty_result_unexpected` | `EMPTY_RESULT_UNEXPECTED` | `--expect-non-empty` declared and the vector result has zero features |
| `check_result_bbox_disjoint_from_input` | `RESULT_BBOX_DISJOINT_FROM_INPUT` | `--compare-to` given and the result's extent doesn't overlap it at all |

## How it fits the overall flow

The judgment layer over `qc_collect.py`'s measurements — `qc.py` never reads
a file or hits the database, `qc_collect.py` never judges anything. `bin/qc`
calls this directly; `exporter.py` calls it after writing an export (and can
turn `EMPTY_RESULT_UNEXPECTED` into a hard failure via `--expect-non-empty`);
`preview.py` reuses `qc_collect`'s collectors so its visual summary agrees
with a QC report by construction.
