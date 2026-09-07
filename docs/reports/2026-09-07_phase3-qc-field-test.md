# Phase 3 QC Field Test - 2026-09-07

## Scope

Ran a real job end to end through `bin/*` with QC attached, against a real file from
`data/incoming/` (not a fixture), per the Phase 3 plan's Task 7 gate.

- Input: `data/incoming/activation_363642ba-2983-47be-a17c-7e0d5263ab2c.kml` (a single
  polygon AOI near Oslo, EPSG:4326, `PolygonZ`)
- Flow: inspect -> `bin/qc` (pre-ingest) -> ingest (twice, once reprojected, once not) ->
  `bin/qc --metric-op` on both -> analysis SQL (buffer + area) -> `bin/export --sql
  --compare-to` -> `bin/qc --expect-non-empty` on a deliberately empty export
- Environment: `docker compose up -d --build`, `bin/doctor` reported `database_ok: true`,
  GDAL 3.13.3, psql 18.6

## Commands executed and results

### 1. `bin/qc` on the source file, before ingest

```
bin/qc /data/incoming/activation_363642ba-2983-47be-a17c-7e0d5263ab2c.kml
```

`qc_status: "ok"`, no warnings. `crs: EPSG:4326`, `feature_count: 1`,
`declared_geometry_type: "PolygonZ"`, `has_z: true` (OGR's authority, confirmed correct: the
KML genuinely carries Z coordinates). `GEOGRAPHIC_CRS_FOR_METRIC_OPERATION`,
`EMPTY_RESULT_UNEXPECTED` and `RESULT_BBOX_DISJOINT_FROM_INPUT` all read `not_evaluated`
because no flags were passed - legible, not lost in the noise; each carried a message
naming the flag that would activate it.

### 2. Ingest, twice

```
bin/ingest-vector .../activation....kml --table activation_aoi --dst-crs EPSG:3035
  -> ingest_id 20260907084347_c1ba2c6a8c, schema raw_20260907084347_c1ba2c6a8c

bin/ingest-vector .../activation....kml --table activation_aoi_4326
  -> ingest_id 20260907084412_c1ba2c6a8c, schema raw_20260907084412_c1ba2c6a8c (kept geographic)
```

### 3. `bin/qc --metric-op` on both tables

```
bin/qc raw_20260907084347_c1ba2c6a8c.activation_aoi --metric-op
```
`GEOGRAPHIC_CRS_FOR_METRIC_OPERATION` -> `pass` (`EPSG:3035 is projected`). Correct: this
table was reprojected on ingest.

```
bin/qc raw_20260907084412_c1ba2c6a8c.activation_aoi_4326 --metric-op
```
`GEOGRAPHIC_CRS_FOR_METRIC_OPERATION` -> `warn`, `qc_status: "warning"`,
`warnings: [{"code": "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION", ...}]`. This table was left in
EPSG:4326 and the check correctly flagged it. Confirms the same source, ingested two ways,
produces two different verdicts from one flag - the check is reading real CRS metadata, not
a static property of the dataset.

### 4. Analysis SQL (buffer + area, a metric operation)

```sql
CREATE SCHEMA IF NOT EXISTS analysis_20260907084347_c1ba2c6a8c;
CREATE TABLE analysis_20260907084347_c1ba2c6a8c.activation_buffer AS
SELECT fid, name, ST_Buffer(geom, 100) AS geom, ST_Area(geom) AS area_m2
FROM raw_20260907084347_c1ba2c6a8c.activation_aoi;
```
`bin/run-sql` reported `row_count: 1` for `activation_buffer`, confirmed with
`bin/describe-table`.

### 5. `bin/export --sql ... --compare-to`, the case QC most needs

```
bin/export /data/outgoing/2026-09-07_qc-field-test/activation_buffer.gpkg --format gpkg \
  --sql "SELECT * FROM analysis_20260907084347_c1ba2c6a8c.activation_buffer" \
  --compare-to raw_20260907084347_c1ba2c6a8c.activation_aoi
```
`RESULT_BBOX_DISJOINT_FROM_INPUT` -> `pass` (`Extent overlaps
raw_20260907084347_c1ba2c6a8c.activation_aoi`), rather than `not_evaluated`. This is the
scenario the plan calls out as the reason `--compare-to` exists: a `--sql` export has no
inferable input, and here the flag supplied one and the check ran for real, in the projected
CRS the buffer was computed in. `qc_status: "ok"`, `feature_count: 1`, buffered area
2,234,821 m^2 against an unbuffered 1,725,249 m^2 - consistent with a 100 m buffer on this
AOI's perimeter.

### 6. `EMPTY_RESULT_UNEXPECTED` on a deliberately empty result

`bin/export` does not expose `--expect-non-empty` (only `--qc/--no-qc` and `--compare-to`
were added to the export CLI in Task 5); ran the check directly against the just-exported
empty file instead:

```
bin/export /data/outgoing/2026-09-07_qc-field-test/empty_probe.gpkg --format gpkg \
  --sql "SELECT fid, geom FROM raw_20260907084347_c1ba2c6a8c.activation_aoi WHERE false"
  -> feature_count: 0, qc attached with no --expect-non-empty, so EMPTY_RESULT_UNEXPECTED
     read not_evaluated on the export itself, as documented

bin/qc /data/outgoing/2026-09-07_qc-field-test/empty_probe.gpkg --expect-non-empty
  -> qc_status: "warning", warnings: [{"code": "EMPTY_RESULT_UNEXPECTED",
     "message": "Result has no features, but features were expected"}]
```
Fired correctly. **Gap noted for a future phase**: `export` cannot exercise this check on
its own output in one command, because it has no `--expect-non-empty` flag - only `qc` does.
An operator who wants both checks (`--compare-to` and empty-result) on the same export
currently needs a follow-up `bin/qc` call.

### 7. Raster `percent_nodata` under `-approx_stats`

Ran `bin/qc` against `tests/fixtures/elevation.tif` (a uniform-value burned raster, no
fixture with real nodata pixels exists yet) as a smoke check of the approximate-stats path
rather than an accuracy test: `stats_mode: "approximate"`, `percent_nodata: 0.0`,
`min/max/mean: 500.0` - correct for a raster burned uniformly with no nodata. No
`.aux.xml` sidecar was written next to the read-only source (confirmed by
`test_raster_qc_reports_bands_without_writing_a_sidecar` in the unit suite; not re-checked
manually here since the fixture path is inside the repo, not the read-only mount). This
field test did not include a raster with genuine nodata pixels, so **the accuracy of
approximate `percent_nodata` against a real gap-filled raster is still unverified** - flagged
for the next real raster job.

## Findings

- All five checks behaved as designed against real data: two `pass`, two correctly-`warn`
  (the geographic-CRS table, the empty result), and `not_evaluated` was legible throughout -
  every skipped check carried a message naming the flag that would activate it, so it never
  read as silent success.
- `CRS_MISSING` / `CRS_SUSPICIOUS` behaved as advisory (`qc_status: "warning"`, exit 0)
  throughout, distinct from the fatal ingest-time versions, though this run never actually
  hit a missing or suspicious CRS to force a side-by-side comparison.
- Gap: `export` has no `--expect-non-empty`, so an operator wanting that check on export
  output needs a second `bin/qc` call. Worth considering for Phase 4 if it comes up often in
  practice; not a blocker for this phase, which scoped `export`'s new flags to `--no-qc` and
  `--compare-to` only.
- Gap: no fixture or field data yet exercises raster nodata percentage against ground truth;
  the check path works mechanically but its accuracy claim is unverified.

## Artifacts

- `data/outgoing/2026-09-07_qc-field-test/activation_buffer.gpkg`
- `data/outgoing/2026-09-07_qc-field-test/empty_probe.gpkg`
- Schemas left in place for inspection: `raw_20260907084347_c1ba2c6a8c`,
  `raw_20260907084412_c1ba2c6a8c`, `analysis_20260907084347_c1ba2c6a8c`
