# Phase 3 — Deterministic QC: design

**Status:** approved design, not yet implemented.
**Plan reference:** `docs/plans/2026-09-04_improvement_plan_revised.md`, "Phase 3 — Deterministic QC (O9)".
**Date:** 2026-09-07.

## Purpose

Give the operator a deterministic answer to "is this dataset, or this result I just
produced, plausible?" without a human inspecting it. The agent checks its own output.

QC reports numbers (metrics) and raises a small set of named warnings when the numbers
contradict the context the caller declared. It never guesses at context.

## Scope

In scope for this phase:

- Local files, vector and raster, read through GDAL and DuckDB.
- PostGIS tables (`raw_<id>.<table>`, `analysis_<id>.<table>`), vector fully, raster
  structurally.
- A `bin/qc` command and a QC block attached to `export` output.

Deferred, deliberately:

- DuckDB / Parquet / GeoParquet URIs as a QC source. The file collector goes through
  DuckDB `ST_Read`, so adding this later is a swap to `read_parquet`, not a new backend.
- PostGIS raster pixel statistics (`ST_SummaryStats`). Raster tables report structure only.
- Extra warning codes (`INVALID_GEOMETRY_PRESENT`, `MIXED_GEOMETRY_TYPES`,
  `DUPLICATE_IDS`, `ALL_NODATA_RASTER`). Metrics report the numbers; deciding a number is
  wrong waits for evidence from real jobs.

## Architecture

```
bin/qc <ref> [--expect-non-empty] [--compare-to <ref>] [--metric-op]
             [--id-column <c>] [--exact-stats]
                      |
              llm_gis/qc.py :: qc_report(ref, context)
                      |
              resolve_source(ref)        path -> file, "schema.table" -> postgis
                      |
   collectors (backend-specific, one normalized dict out)
     _file_vector_metrics    ogrinfo (CRS, declared type, layers)
                             + DuckDB ST_Read (one streaming aggregate pass)
     _file_raster_metrics    gdalinfo, -approx_stats, GDAL_PAM_ENABLED=NO
     _table_vector_metrics   one SQL query via common.db_connect
     _table_raster_metrics   structural only (raster_columns, ST_Metadata)
                      |
              run_checks(metrics, context)     pure functions, no I/O
                      |
              {status, source, metrics, checks, warnings, created_at}
```

`llm_gis/qc.py` holds `qc_report`, four private collectors and a `CHECKS` list. The
collector/check seam is the design: every warning code is exercisable from a plain dict,
with no database, no GDAL and no fixture file.

Rationale for rejected structures: putting checks inside each backend duplicates logic and
forces a live backend to test a warning; a declarative check registry is over-built for
five checks, the same judgement the plan's D4 applies to the engine registry.

## Normalized metrics shape

```json
{"source": {"kind": "file|postgis_table", "ref": "...", "dataset_kind": "vector|raster"},
 "crs": "EPSG:3035",
 "bbox": {"minx": 0, "miny": 0, "maxx": 1, "maxy": 1},
 "vector": {"feature_count": 128,
            "geometry_types": {"POLYGON": 128},
            "empty_count": 0,
            "invalid_count": 2,
            "has_z": false,
            "has_m": false,
            "area_stats": {"min": 0, "max": 0, "mean": 0, "sum": 0},
            "length_stats": null,
            "null_counts": {"name": 3},
            "duplicate_id_count": 0,
            "id_column": "fid"},
 "raster": {"width": 256, "height": 256, "band_count": 1,
            "resolution": {"x": 10.0, "y": 10.0},
            "bands": [{"index": 1, "nodata": -9999, "min": 0, "max": 1,
                       "mean": 0.5, "percent_nodata": 3.2}],
            "stats_mode": "approximate|exact|none"}}
```

Rules:

- `area_stats` for polygonal data, `length_stats` for linear data, neither for points.
  Chosen by dominant geometry dimension. The unused key is `null`.
- `null_counts` covers every non-geometry column, computed in the same aggregate pass.
- `duplicate_id_count` defaults to `fid` for PostGIS tables (the ingest contract
  guarantees it) and is skipped for files unless `--id-column` is given.
- `crs` is normalized through `common.normalize_crs`.
- Raster statistics are approximate by default (`-approx_stats`), bounding cost.
  `--exact-stats` opts into a full pixel scan. `GDAL_PAM_ENABLED=NO` is set so GDAL never
  attempts a `.aux.xml` sidecar write, which would fail against the read-only
  `/data/incoming` mount.

## Result envelope

```json
{"status": "ok|warning",
 "source": {"kind": "file", "ref": "/data/outgoing/x.gpkg", "dataset_kind": "vector"},
 "metrics": {},
 "checks": [{"code": "EMPTY_RESULT_UNEXPECTED",
             "severity": "warning",
             "result": "pass|warn|not_evaluated",
             "message": "..."}],
 "warnings": [],
 "created_at": "2026-09-07T00:00:00Z"}
```

`warnings` is the plan's flat `[{code, message, severity}]` list, containing exactly the
checks whose `result` is `warn`. `checks` is additive and exists so that `not_evaluated` is
visible: a caller must never read an empty `warnings` list as "checked and clean" when the
check was in fact skipped for want of context.

`status` is `warning` when any check warns, otherwise `ok`. QC never raises on a data
problem. It raises `GisError` only when a source cannot be read, per the Phase 1 CLI
contract.

## Checks

| Code | Fires when | Context required |
|---|---|---|
| `CRS_MISSING` | `common.crs_status` returns `missing` | none |
| `CRS_SUSPICIOUS` | `common.crs_status` returns `suspicious`; its `crs_reasons` become the message | none |
| `GEOGRAPHIC_CRS_FOR_METRIC_OPERATION` | CRS is geographic and `--metric-op` was given | `--metric-op`, else `not_evaluated` |
| `EMPTY_RESULT_UNEXPECTED` | `feature_count == 0` and `--expect-non-empty` was given | flag, else `not_evaluated` |
| `RESULT_BBOX_DISJOINT_FROM_INPUT` | the subject bbox and the reference bbox do not intersect | `--compare-to`, else `not_evaluated`; also `not_evaluated` if either bbox is null |

The first two are `common.crs_status` surfaced as warnings rather than reimplemented. This
is the plan's "extends `crs_status`" instruction made concrete: `qc.py` calls the existing
function and maps its two non-ok states onto the existing `errors.py` code constants
`CRS_MISSING` and `CRS_SUSPICIOUS`. No CRS plausibility logic is written twice.

`RESULT_BBOX_DISJOINT_FROM_INPUT` reprojects the reference bbox with `pyproj` (already a
dependency) when the two CRSs differ. Comparison is a plain rectangle intersection test.

Context is always explicit. QC does not consult `meta.ingestions` to infer an input:
implicit lineage fails opaquely when it is absent and couples QC to the PostGIS metadata
schema.

## Export integration

`exporter.export_result` gains `qc: bool = True`, exposed as `--no-qc` on the CLI. When on,
it runs `qc_report` over the file it has just written and attaches the result as a `qc`
key.

Export supplies `compare_to` itself, set to its own `--table`. This is not hidden lineage:
it is the command's own declared input. When the export was driven by `--sql` instead,
`compare_to` is omitted and `RESULT_BBOX_DISJOINT_FROM_INPUT` reports `not_evaluated`,
because establishing the query's extent honestly would mean executing the query twice.

The existing `feature_count`, `crs`, `output_path`, `output_format`, `table` and `sql` keys
are unchanged and stay at the top level. The `qc` block is purely additive, so the Phase 0
and Phase 1 output-contract tests continue to pass unmodified.

`--no-qc` exists for the case where the extra scan over a very large export is not worth
its cost.

## Testing

- `tests/test_qc_checks.py` — all five codes driven from hand-written metrics dicts,
  asserting `pass`, `warn` and `not_evaluated` for each. No I/O. This is the test that
  satisfies the plan's "warning codes covered by fixture tests".
- `tests/test_qc_file.py` — the real file collectors against the Phase 0 GeoPackage and
  GeoTIFF fixtures, plus one new small fixture carrying a self-intersecting polygon and a
  null attribute value, so `invalid_count` and `null_counts` are exercised against real
  data.
- `tests/live/test_qc_postgis.py` — the table collector and the export-attached QC block,
  marked `live`, excluded from the default run.

All non-live tests must pass on the host with no database and no network.

## Documentation

Per O22, shipped with the phase, not after it: `README.md`, `AGENTS.md` and
`.claude/skills/hot-start/SKILL.md` gain the `bin/qc` command, the warning-code table and
the note that `export` now returns a `qc` block.

## Field test

Per the plan's standing rule, the phase is done only after a real job runs end to end
through `bin/*` with QC attached, and the findings are written to `docs/reports/`.

## Open question carried forward

Whether `bin/qc` should also accept a Parquet or GeoParquet URI is deferred, not decided
against. The ST_Read-based file collector was chosen specifically so that answering "yes"
later costs one function, not a backend.
