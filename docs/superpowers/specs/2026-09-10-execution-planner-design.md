# Phase 6 — Execution strategy layer: design

**Status:** approved design, not yet implemented.
**Plan reference:** `docs/plans/2026-09-04_improvement_plan_revised.md`, "Phase 6 — Execution
strategy layer (O4, O10)".
**Date:** 2026-09-10.

## Purpose

Two engines now serve this workspace, and for some sources both of them work. `llm_gis/planner.py`
decides which one a job should use, says why in a sentence a person can argue with, and prints
the serial list of `bin/*` steps that carry the decision out. It executes nothing.

The plan defers this phase past both engines by D5: rules written before the engines are in
real use are guesses with a `reason` string attached. Phases 2 and 4 are now in use, and this
document records what they turned out to decide.

## The finding that shapes this phase

The plan assumed the two engines partition by format — DuckDB for Parquet, PostGIS for
everything ingested — which would make a planner a lookup table wearing architecture's clothes,
exactly what D4 rejects for a registry.

They do not partition. `llm_gis/duck.py:reader_sql` picks `ST_Read(?)` for any source whose
suffix is not Parquet, and `llm_gis/qc_collect.py:132` uses it in production: `bin/qc` reads a
GeoPackage through DuckDB spatial, with no database, covered offline by `tests/test_qc_cli.py`.

So a local vector file has two live routes today:

- DuckDB `ST_Read` — one command, no database, nothing persists.
- `stage` → `ingest-vector` → `run-sql` → `export` — indexed, reprojectable, reusable, and
  available to every later step of a job.

Both work. Neither is better in general. **What separates them is whether the result has to
survive the command that produced it.** That is the axis this phase encodes, and it is the only
one.

Two further facts, both verified on 2026-09-10 rather than assumed, constrain the rules below:

- GDAL in this workspace has no Parquet driver (`ogrinfo --formats` lists GPKG and FlatGeobuf,
  no Parquet). Nothing on the ogr2ogr ingest path can open a Parquet file.
- DuckDB spatial here can write GPKG: `COPY t TO '...gpkg' (FORMAT GDAL, DRIVER 'GPKG')`
  succeeds. A Parquet-to-PostGIS path therefore exists in principle, but no command exposes it —
  `duck-query --output` writes Parquet only.

## What the planner does not do

Recorded first, because a planner accretes ambition faster than it accretes rules.

- **It does not execute.** `bin/plan` prints a plan and exits. The caller runs the steps, or
  does not. An explainer that grows execution features stops being an explainer, and the plan
  says "serial plan, no DAG engine".
- **It does not route on size.** Neither byte size nor row count branches any rule. Routing on
  size means choosing a threshold, and a threshold chosen before anyone has been hurt by the
  wrong one is the guess D5 warns about. Size may appear in the output as a note; it never
  decides.
- **It does not open the source.** `classify` reads the URI's suffix and scheme and nothing
  else. The whole module is pure, so the whole test suite runs with no database and no network,
  honestly rather than by mocking.
- **It does not optimise.** There is no cost model and no second-guessing an override.
- **It does not fix the gaps it finds.** Where no route exists, it says so precisely and stops.

## Scope

In scope:

- `llm_gis/planner.py` — `classify`, `readers`, `route`, `steps`, and the rule table.
- `bin/plan` and its `cli.py` command, following the existing wrapper idiom.
- `catalog.py` gains a `readers` field on flattened assets; `readable_by` keeps its current
  values, re-expressed as a projection of the planner's answer (see "One table, two fields").
- `tests/test_planner.py` — rule table, overrides, classification, blocked cases.
- `docs/llm/OUTPUT_SCHEMA.md` gains a `bin/plan` entry.

Out of scope, deliberately:

- Any new flag on `duck-query`, including the output-format flag that would unblock
  Parquet-to-PostGIS. That is a Phase 2 change and this phase reports the gap instead.
- Raster routing. `bin/plan` refuses raster sources; Phase 7 owns cloud raster.
- Any change to what `duck-query`, `run-sql`, `export` or `qc` do when run.
- An engine capability registry. The rule table below is the registry, and it earns its place by
  deciding something rather than describing something.

## The module

Three functions and two dataclasses. No I/O, no state.

### `classify(uri) -> Source`

`Source` carries `uri`, `format`, `locality` and `readers`.

| `format` | recognised by | `readers` |
|---|---|---|
| `parquet` | suffix `.parquet`, `.geoparquet`, `.pq` | `["duckdb"]` |
| `vector_file` | any other GDAL vector suffix | `["duckdb", "postgis"]` |
| `postgis_table` | `schema.table` form, no suffix, no scheme | `["postgis"]` |
| `raster` | suffix `.tif`, `.tiff`, `.vrt` | `[]` |

`locality` is `remote` for `http://`, `https://` and `s3://`, `local` otherwise.

`readers` states what can open the source, not what should — the same distinction Phase 4 drew
for `readable_by`. `vector_file` reports `postgis` because `ingest-vector` can load it, not
because it is already loaded.

### `route(operation, source, materialise, engine) -> Route`

`Route` carries `strategy`, `reason`, `fallback`, `overridden` and `warnings`.

Operations are `query`, `analyse`, `export`. Nothing else is admitted: `describe`, `qc`,
`inspect` and the `catalog-*` family each have exactly one route, and an operation with one
route has no business in a planner.

| operation | source | `--materialise` | strategy | reason |
|---|---|---|---|---|
| `query` | `parquet` | no | `duckdb` | reads in place; no database needed |
| `query` | `parquet` | yes | *none* | see "The blocked case" |
| `query` | `vector_file`, local | no | `duckdb` | `ST_Read` opens it without ingesting |
| `query` | `vector_file`, local | yes | `postgis` | the result must survive for later steps |
| `query` | `vector_file`, remote | no | `duckdb` | plus `REMOTE_UNINDEXED_READ` warning |
| `query` | `vector_file`, remote | yes | `postgis` | download and ingest; the result is reused |
| `query` | `postgis_table` | — | `postgis` | already in the workspace |
| `analyse` | `vector_file` or `postgis_table` | — | `postgis` | SQL across sources needs the persistent workspace |
| `analyse` | `parquet` | — | *none* | see "The blocked case" |
| `export` | `postgis_table` | — | `postgis` | `bin/export` owns this |
| `export` | `parquet` or `vector_file` | — | `duckdb` | the source never enters the database |
| any | `raster` | — | *error* | `UNSUPPORTED_FORMAT`; Phase 7 owns cloud raster |

`materialise` defaults to `False`. `analyse` ignores it: crossing sources in SQL is what the
persistent workspace is for, so the route is `postgis` whether or not anyone asked.

`fallback` names the other viable engine as `{strategy, requires, loses}` where one exists, and
is `null` otherwise. For the local GeoPackage query it reads
`{strategy: "postgis", requires: "stage and ingest-vector first", loses: null}` in one direction
and `{strategy: "duckdb", requires: null, loses: "persistence"}` in the other. `requires` is the
work the fallback costs; `loses` is the property the fallback gives up.

### `steps(operation, route, arguments) -> list[Step]`

Each `Step` is `{command, argv, why}`. `argv` is what follows `bin/`, carrying the caller's real
`--bbox`, `--where`, `--format` and `--output` values, so the printed lines paste and run.

## Output shape

Phase 1's envelope; Phase 3's `{code, message, severity}` warnings.

```json
{
  "operation": "query",
  "source": {"uri": "...", "format": "vector_file", "locality": "local",
             "readers": ["duckdb", "postgis"]},
  "strategy": "duckdb",
  "reason": "ST_Read opens a local vector file without ingesting it, and no persistence was requested",
  "fallback": {"strategy": "postgis", "requires": "stage and ingest-vector first", "loses": null},
  "overridden": null,
  "warnings": [],
  "steps": [
    {"command": "duck-query",
     "argv": ["/data/incoming/aoi.gpkg", "--bbox", "8.5,45.0,9.5,45.6", "--output", "/data/outgoing/...parquet"],
     "why": "filter in place and write the matches"}
  ]
}
```

`strategy` is `null` on a blocked route; `steps` is then empty and `blocked_by` carries the
prerequisite. Every other key is present always, so a caller never guards for a missing one.

## The blocked case

`bin/plan query <parquet> --materialise` and `bin/plan analyse <parquet>` have no route today,
and the planner says exactly why rather than inventing one:

```json
{"strategy": null,
 "blocked_by": {
   "code": "NO_CONVERSION_PATH",
   "message": "Nothing here writes a GDAL-readable file from a Parquet source: GDAL in this image has no Parquet driver, and duck-query --output writes Parquet.",
   "suggested_action": "Query in place without --materialise, or add a GPKG output format to duck-query (DuckDB supports COPY ... FORMAT GDAL)."}}
```

This is a report, not an error: exit 0, a plan object saying no plan exists. The gap is one flag
on `duck-query` and belongs to Phase 2's surface, not to an explainer. Surfacing it in
machine-readable form on day one is the planner earning its keep.

## Overrides

`--engine duckdb|postgis` and `--materialise/--no-materialise` beat the rule table, and the
output records which one won in `overridden`.

An override the source cannot honour is a `GisError`, never a silent fallback:

- `--engine postgis` on a remote href — nothing ingests a URI in place.
- `--engine duckdb` on a `postgis_table` — DuckDB does not read the workspace's tables.

`--engine postgis` on a `parquet` source is not an error: it is the blocked case, and it returns
the same `NO_CONVERSION_PATH` report the rules produce. An override cannot conjure a route that
does not exist, and the honest answer to "use PostGIS for this Parquet file" is the prerequisite,
not a refusal.

Refusing loudly matters more here than anywhere else in the workspace: an override is someone
saying they know better, and quietly routing around them destroys the only signal that they were
wrong.

`--materialise` exists on `bin/plan` alone. `duck-query` keeps `--output` unchanged; a second
flag meaning nearly the same thing on the same command is how a CLI becomes unlearnable.

## One table, two fields

Phase 4's design records that `readable_by` "is nonetheless planner-shaped" and that Phase 6
"subsumes this field — it must not become a second, competing routing table."

It is subsumed without changing what it returns. `planner.readers()` becomes the single
authoritative table, and `catalog.py:readable_by()` becomes a documented projection of it:

```
readable_by = ["duckdb"] if format == "parquet" else []
```

Values are byte-for-byte what they are today, every existing test and consumer keeps working,
and there is still exactly one place where format-to-engine knowledge lives. Flattened assets
gain a sibling field, `readers`, carrying the planner's fuller answer — a GeoPackage asset
reports `readable_by: []` and `readers: ["duckdb", "postgis"]`.

The two fields differ on purpose and the schema doc says so: `readable_by` answers "can Phase 2's
query path consume this href directly", which for a GeoPackage over HTTP is still no; `readers`
answers "what could open this at all". A future phase may retire `readable_by`; this one does
not.

## The `--asset` input

`bin/plan --asset <file.json>` accepts an `Asset` as emitted by `duck-describe`, `inspect` or
`catalog-assets`. This is the Phase 5 linkage the asset model was extracted for.

It is optional and it never changes the route. Its measured fields add warnings the URI alone
cannot support — a geographic CRS for a metric operation, an empty `record_count` before an
export — and nothing more. Routing on measurements would mean `bin/plan` needs a described asset
to answer at all, and for a STAC asset nobody has opened, Phase 5's model deliberately reports
`None` for nearly everything. The planner must work at discovery time, when the least is known.

Advertised values are never read. A publisher's claim is not a measurement, and Phase 4
quarantined them for that reason.

## Errors

Reused: `UNSUPPORTED_FORMAT` (raster source), `MISSING_ARGUMENT` (an operation missing an
argument its steps need), `INPUT_NOT_FOUND` — only when `--asset` names a file that is not there,
since the planner does not stat the source itself.

New: none. `NO_CONVERSION_PATH` is a `blocked_by` code inside a successful plan, not an error
code, because "there is no route" is an answer to the question asked.

An override the source cannot honour raises `UNSUPPORTED_FORMAT` with the requested engine and
the source's `readers` in `details`.

## Testing

`tests/test_planner.py`, entirely offline — no database, no network, no fixtures beyond URI
strings, because the module opens nothing.

- One case per row of the rule table, asserting `strategy` and the presence of a `reason`.
- `classify` per format and per scheme, including a suffix with a query string
  (`...parquet?token=x`), which `duck.py:reader_sql` already handles by splitting on `?`.
- Overrides beat rules and set `overridden`.
- Each impossible override raises `UNSUPPORTED_FORMAT`.
- Both blocked cases return `strategy: null`, `steps: []` and the `NO_CONVERSION_PATH` code.
- `steps()` carries `--bbox` and `--where` through into `argv` verbatim.
- `catalog.py`: existing `readable_by` assertions pass unchanged; one new case asserts a
  GeoPackage asset reports `readable_by: []` and `readers: ["duckdb", "postgis"]`.

## Documentation

`docs/llm/OUTPUT_SCHEMA.md` gains a `bin/plan` section covering the plan object, the `blocked_by`
shape, and the `readable_by` / `readers` distinction. `docs/llm/QUICKSTART.md` gains one line:
plan first when a job could go either way.

## Done when

`bin/plan` explains, in one machine-readable object, why a route was chosen for each of:

1. The Phase 2 workflow — a bbox query against a remote GeoParquet asset: `duckdb`, no
   materialisation, fallback `null`.
2. The Phase 4 workflow — a STAC-discovered GeoParquet href: the same route, reached from an
   href rather than a path.
3. A local GeoPackage query without `--materialise`: `duckdb`, fallback `postgis`.
4. The same with `--materialise`: `postgis`, four steps, fallback `duckdb` losing persistence.
5. `query <parquet> --materialise`: blocked, with the prerequisite named.

Field test, per the plan's standing rule: run a real job through `bin/plan`, then run its emitted
steps verbatim. A plan whose steps do not paste and run is the failure this phase most needs to
catch, and only a field test catches it.
