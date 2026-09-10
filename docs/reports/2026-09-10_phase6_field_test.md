# Phase 6 Execution Planner Field Test - 2026-09-10

## Scope

Ran the plan's five done-when cases through `bin/plan` against real sources (a public
Overture GeoParquet asset discovered via STAC, and local fixtures copied into
`data/incoming/` for the run), then executed a materialised plan's emitted steps verbatim
to confirm they paste and run unedited, per the plan's standing field-test rule.

- Environment: `docker compose up -d --build`, `bin/doctor` reported `database_ok: true`,
  GDAL 3.13.3, psql 18.6
- Local sources: `tests/fixtures/aoi.gpkg` and `tests/fixtures/aoi.parquet` copied to
  `data/incoming/aoi.gpkg` and `data/incoming/aoi.parquet` for the duration of the test
  (removed afterwards; `data/incoming/` holds no leftover files from this run)
- Network: the agent container reached `stac.overturemaps.org` and the Overture S3 bucket
  directly

## The five done-when cases

### 1 and 2. The Phase 2/4 workflow: a bbox query against a remote GeoParquet asset

Discovered via `bin/catalog-search overture --collection building --bbox 10.6,59.8,10.9,60.0
--limit 1` then `bin/catalog-assets <self-href> --role data`, exactly as Phase 4's field
test did. The `aws` asset's href fed straight into `bin/plan query <href> --bbox
10.6,59.8,10.9,60.0`:

```json
{"strategy": "duckdb", "fallback": null,
 "reason": "DuckDB reads Parquet in place; no database is needed",
 "steps": [{"command": "duck-query", "argv": ["<href>", "--bbox", "10.6,59.8,10.9,60.0"]}]}
```

Matches the done-when exactly: `duckdb`, no materialisation, `fallback: null`. Since the
href was reached through `catalog-assets` rather than typed by hand, this is also case 2 —
the STAC route lands on the same answer as a bare path. The same asset's `catalog-assets`
entry reports `readable_by: ["duckdb"]` and `readers: ["duckdb"]` — they agree because a
Parquet asset genuinely has one reader.

### 3. A local GeoPackage query without `--materialise`

`bin/inspect /data/incoming/aoi.gpkg` first, to get a real bbox: `crs_status: ok`, extent
`10.0,45.0,10.3,45.3`. Then:

```
bin/plan query /data/incoming/aoi.gpkg
```

```json
{"strategy": "duckdb",
 "fallback": {"strategy": "postgis", "requires": "stage and ingest-vector first", "loses": null},
 "reason": "ST_Read opens a vector file without ingesting it, and no persistence was requested"}
```

Matches: `duckdb`, fallback names `postgis`.

### 4. The same with `--materialise`

```
bin/plan query /data/incoming/aoi.gpkg --materialise --bbox 10.0,45.0,10.3,45.3 \
  --output /data/outgoing/2026-09-10_phase6/result.gpkg
```

```json
{"strategy": "postgis",
 "fallback": {"strategy": "duckdb", "requires": null, "loses": "persistence"},
 "steps": [
   {"command": "stage", "argv": ["/data/incoming/aoi.gpkg", "--ingest-id", "aoi"]},
   {"command": "ingest-vector",
    "argv": ["/data/work/staging/aoi/aoi.gpkg", "--table", "aoi", "--ingest-id", "aoi"]},
   {"command": "export",
    "argv": ["/data/outgoing/2026-09-10_phase6/result.gpkg", "--format", "gpkg", "--sql",
             "SELECT * FROM raw_aoi.aoi WHERE ST_Intersects(geom, ST_MakeEnvelope(10.0,45.0,10.3,45.3, ST_SRID(geom)))"]}
 ]}
```

Matches: `postgis`, three steps, fallback `duckdb` losing persistence.

### 5. `query <parquet> --materialise`: blocked

```
bin/plan query /data/incoming/aoi.parquet --materialise
```

```json
{"strategy": null, "steps": [],
 "blocked_by": {"code": "NO_CONVERSION_PATH", "message": "...", "suggested_action": "..."}}
```

Exit code 0 (checked directly: `echo $?` after the call returned `0`). `status: "ok"` in the
envelope — a blocked plan is a successful answer, not an error, exactly as designed.

## Running case 4's emitted steps verbatim

Took the three `argv` values above and ran each as `bin/<command> <argv...>`, changing
nothing:

```
bin/stage /data/incoming/aoi.gpkg --ingest-id aoi
  -> staged_item: /data/work/staging/aoi/aoi.gpkg   (matches step 2's input path exactly)

bin/ingest-vector /data/work/staging/aoi/aoi.gpkg --table aoi --ingest-id aoi
  -> schema: raw_aoi, table: aoi, feature_count: 4, crs_status: ok
     (matches "raw_aoi.aoi" in step 3's --sql exactly)

bin/export /data/outgoing/2026-09-10_phase6/result.gpkg --format gpkg --sql \
  "SELECT * FROM raw_aoi.aoi WHERE ST_Intersects(geom, ST_MakeEnvelope(10.0,45.0,10.3,45.3, ST_SRID(geom)))"
  -> feature_count: 4, qc_status: ok, warnings: []
```

All three steps pasted and ran unedited: the ingest id `aoi` the plan derived from the file
stem was accepted by `stage` and reused by `ingest-vector` and by the export SQL without any
manual substitution, and `bin/list-ingestions` confirms exactly one new row, `ingest_id:
"aoi"`. This is the risk the plan's Task 3 self-review note flagged (a printed timestamped
id would have made this unpasteable) and the field test found no case where it broke.

## Confirming the Phase 4 route from an href

Already covered by cases 1/2 above: the href taken from `catalog-assets` output routed
through `bin/plan` to `strategy: "duckdb"` with a `duck-query` step naming that exact href
verbatim (checked programmatically: the href string is a member of the step's `argv` list).
The same asset's `readable_by` and `readers` values were both `["duckdb"]`, confirming the
narrowing only shows up for formats `readable_by` doesn't cover (GeoPackage, in case 3/4).

## What the run surfaced that the suite could not

Nothing broke. The offline suite already exercises the ingest-id derivation and the exact
SQL string byte-for-byte (Task 3's tests assert the `ST_MakeEnvelope` fragment and the
staged path), so this field test's job was narrower than Phase 4's: confirm those strings
survive contact with the real `bin/stage` / `bin/ingest-vector` / `bin/export` argument
parsers, not just the planner's own output. They did, without incident. The one thing a unit
test genuinely could not have checked — whether `stage --ingest-id aoi` and `ingest-vector
--ingest-id aoi` actually agree on where the file lands and what schema it creates when run
for real against a live database — is exactly what this test proved.

No findings for a future phase. No code changed as a result of this test.

## Deliverable

`data/outgoing/2026-09-10_phase6/result.gpkg` — the 4-feature `aoi` fixture, materialised
through PostGIS and filtered by its own bbox, produced entirely from `bin/plan`'s case-4
step list run verbatim.
