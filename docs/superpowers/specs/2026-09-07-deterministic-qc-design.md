# Phase 3 — Deterministic QC: design

**Status:** approved design, revised after review, not yet implemented.
**Plan reference:** `docs/plans/2026-09-04_improvement_plan_revised.md`, "Phase 3 — Deterministic QC (O9)".
**Date:** 2026-09-07.

## Purpose

Give the operator a deterministic answer to "is this dataset, or this result I just
produced, plausible?" without a human inspecting it. The agent checks its own output.

QC reports numbers (metrics) and raises a small set of named warnings when the numbers
contradict the context the caller declared. It never guesses at context.

## Scope

In scope for this phase:

- Local files, vector and raster, read through GDAL and DuckDB. This includes local
  Parquet and GeoParquet, because `export --format parquet` already exists on `main` and
  QC is attached to export by default (see "Parquet is a first-class QC source" below).
- PostGIS tables (`raw_<id>.<table>`, `analysis_<id>.<table>`), vector fully, raster
  structurally.
- A `bin/qc` command and a QC block attached to `export` output.

Deferred, deliberately:

- Remote URIs (`https://`, `s3://`) as a QC source. The collector reads them the same way
  once allowed; what is deferred is unbounded network cost inside a default-on export
  check, not the code path.
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
                             + DuckDB aggregate pass, reader chosen by extension:
                               .parquet -> read_parquet, everything else -> ST_Read
     _file_raster_metrics    gdalinfo, -approx_stats, GDAL_PAM_ENABLED=NO
     _table_vector_metrics   schema query + aggregate query via common.db_connect
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

## Parquet is a first-class QC source

`export --format parquet` landed in Phase 2 and QC is on by default, so a Parquet export
reaches the file collector on day one whether or not Parquet is nominally in scope.
`ST_Read` is GDAL-backed and the agent image has no Parquet driver — verified on
2026-09-07, `ogrinfo --formats` in the `agent` service lists only ADBC for Arrow, which is
also why `exporter.py` writes a temporary GeoPackage and converts it through DuckDB. An
`ST_Read`-only collector would therefore fail outright on exactly the files Phase 2 just
taught the system to produce.

The fix is the one-function swap the original design anticipated for later, pulled forward:
`_file_vector_metrics` selects its DuckDB reader by file extension, `read_parquet` for
`.parquet` and `.geoparquet`, `ST_Read` otherwise. The aggregate expressions are identical
either way. `duck.describe` already reads Parquet and derives CRS from GeoParquet `geo`
metadata, so the CRS branch reuses `duck._crs_from_geo_metadata` rather than `ogrinfo`,
which cannot open the file at all.

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
- `null_counts` covers every non-geometry column. This needs the column list before the
  aggregate can be built, so both the PostGIS and the DuckDB collector run **two** queries:
  a schema query (`information_schema.columns`, or DuckDB `DESCRIBE`, as `duck.describe`
  already does) and then one aggregate pass with a `count(*) FILTER (WHERE col IS NULL)`
  term per column. Two queries, not one.
- `duplicate_id_count` defaults to `fid` for PostGIS tables (the ingest contract
  guarantees it) and is skipped for files unless `--id-column` is given.
- `crs` is normalized through `common.normalize_crs`.
- Raster statistics are approximate by default (`-approx_stats`), bounding cost.
  `--exact-stats` opts into a full pixel scan. `GDAL_PAM_ENABLED=NO` is set so GDAL never
  attempts a `.aux.xml` sidecar write, which would fail against the read-only
  `/data/incoming` mount.
- `percent_nodata` derives from GDAL's `STATISTICS_VALID_PERCENT`, which under
  `-approx_stats` is computed from the same subsampled pass as `min`, `max` and `mean`. It
  is an estimate, not a count. `stats_mode` labels the whole `bands` block, `percent_nodata`
  included, and a reader must not treat an approximate `percent_nodata` of 0 as proof that
  no nodata pixels exist.

### Collector agreement, to be verified during implementation

DuckDB spatial's view of a GeoPackage or Shapefile is not guaranteed to match OGR's for
`has_z`, `has_m` and the geometry-type enumeration: `ST_Read` may normalise or flatten
dimensionality, and its type names need not equal OGR's declared layer type. Before
`_file_vector_metrics` relies on the DuckDB values for those three fields, the
implementation must compare them against `ogrinfo -json` output on the Phase 0 GeoPackage
fixture plus a 3D fixture. Where they disagree, `ogrinfo`'s declared values win for
`geometry_types`, `has_z` and `has_m`, and DuckDB supplies only the row-level aggregates
(counts, validity, emptiness, extent, area/length, nulls, duplicates). This check is a task
in the implementation plan, not an assumption in this design.

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

`severity` is `"warning"` for all five checks in this phase. The field carries no
information yet and is kept because the plan specifies it and because a later check that
should stop a workflow needs somewhere to say so. Callers should branch on `code`, not on
`severity`, until a second value exists.

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

**The same code name carries a different severity in QC than in ingest.** `ingest_vector`
and `ingest_raster` raise `CRS_MISSING` and `CRS_SUSPICIOUS` as `GisError`, which is fatal:
the ingest refuses to proceed until the caller supplies `--src-crs`. In a QC report the
identical codes are advisory, arriving inside `warnings` with `status: "warning"` and exit
code 0. A caller must therefore read the envelope, not the code alone: a `code` inside
`warnings` describes an observation, a `code` inside an `{"status": "error"}` object
describes a refusal. Reusing the names is deliberate, so that one vocabulary describes one
condition, but the distinction must be documented wherever the codes are listed.

`RESULT_BBOX_DISJOINT_FROM_INPUT` reprojects the reference bbox with
`pyproj.Transformer.transform_bounds` (already a dependency) when the two CRSs differ.
`transform_bounds` densifies the edges before transforming; transforming the four corners
alone produces a wrong rectangle whenever the projection curves an edge, which across
projected-to-geographic conversions yields both false disjoints and false intersections.
The comparison itself is then a plain rectangle intersection test.

Context is always explicit. QC does not consult `meta.ingestions` to infer an input:
implicit lineage fails opaquely when it is absent and couples QC to the PostGIS metadata
schema.

## Export integration

`exporter.export_result` gains `qc: bool = True`, exposed as `--no-qc` on the CLI, plus its
own `--compare-to <ref>` flag. When QC is on, export runs `qc_report` over the file it has
just written and attaches the result as a `qc` key.

The reference bbox is resolved in this order:

1. `--compare-to <ref>`, when given. This is the flag that makes the check worth having.
2. Otherwise, for a `--table` export, the source table. Kept for zero-effort coverage, but
   it is close to a tautology: a straight table dump cannot be spatially disjoint from
   itself, so a `pass` here is weak evidence. It catches only a reprojection or driver
   fault between the table and the written file.
3. Otherwise, for a `--sql` export, nothing, and the check reports `not_evaluated`.

Case 3 is the reason `--compare-to` exists. A `--sql` export is exactly where a bad join,
an inverted filter or a wrong-CRS predicate produces a result in the wrong place on Earth,
and it is also the case where the command cannot infer an input, since establishing the
query's own extent would mean executing the query twice. So the operator declares it:
`export ... --sql "..." --compare-to raw_<id>.parcels`. This is the same explicit-context
philosophy the `bin/qc` flags follow, applied to the command that most needs it.

The existing `feature_count`, `crs`, `output_path`, `output_format`, `table` and `sql` keys
are unchanged and stay at the top level. The `qc` block is purely additive, so the Phase 0
and Phase 1 output-contract tests continue to pass unmodified.

`--no-qc` exists for the case where the extra scan over a very large export is not worth
its cost.

## Testing

- `tests/test_qc_checks.py` — all five codes driven from hand-written metrics dicts,
  asserting `pass`, `warn` and `not_evaluated` for each. No I/O, no DuckDB. This is the
  test that satisfies the plan's "warning codes covered by fixture tests".
- `tests/test_qc_file.py` — the real file collectors against the Phase 0 GeoPackage and
  GeoTIFF fixtures, a small GeoParquet fixture exercising the `read_parquet` branch, a 3D
  fixture for the `has_z` agreement check, and one fixture carrying a self-intersecting
  polygon and a null attribute so `invalid_count` and `null_counts` see real data.
- `tests/live/test_qc_postgis.py` — the table collector and the export-attached QC block,
  marked `live`, excluded from the default run.

The non-live tests need no database and no network **with one caveat inherited from
`tests/test_duck.py`**: the DuckDB `spatial` extension must already be present in the
extension directory, since `duck.connect` runs `INSTALL spatial` and a cold cache reaches
the network. On a warm cache, and in the container where the cache is a persisted volume,
the suite is offline. `tests/test_qc_checks.py` is unaffected either way, which is why the
warning-code coverage lives there rather than in the collector tests.

## Documentation

Per O22, shipped with the phase, not after it: `README.md`, `AGENTS.md` and
`.claude/skills/hot-start/SKILL.md` gain the `bin/qc` command, the warning-code table, the
note that `export` now returns a `qc` block and accepts `--compare-to` and `--no-qc`, and
the warning-versus-error distinction for the two CRS codes.

## Field test

Per the plan's standing rule, the phase is done only after a real job runs end to end
through `bin/*` with QC attached, and the findings are written to `docs/reports/`.
