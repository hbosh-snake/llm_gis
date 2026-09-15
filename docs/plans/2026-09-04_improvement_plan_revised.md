# llm_gis evolution — revised plan

**Supersedes:** `docs/plans/2026-09-04_improvement_plan.md` (referred to below as "the
original"; its section numbers are cited as O1..O25).

**Goal:** make `llm_gis` able to analyse remote, cloud-native datasets without forcing
every byte through `data/incoming` and PostGIS, while keeping the existing local-file
workflow working unchanged.

**Thesis kept from the original (O-Definition of success):** PostGIS remains a major
analytical engine but stops being the mandatory gateway every dataset must pass through.

**Thesis changed:** the original sequences the work abstraction-first (O1, O19 Phase A).
This plan sequences it capability-first and extracts abstractions from working code.
Rationale in "Departures" below.

---

## 1. Baseline — what exists today

Measured on `main` at `2709d98`, 2026-09-04.

| Item | State |
|---|---|
| Python package | `llm_gis/`, 9 modules, ~970 lines total |
| Commands | `stage`, `inspect`, `ingest-vector`, `ingest-raster`, `run-sql`, `export`, `doctor`, `list-ingestions`, `describe-table` |
| `bin/*` | 3-line wrappers: `docker compose run --rm agent uv run llm-gis <cmd>` |
| Runtime deps | `geopandas`, `psycopg[binary]`, `pydantic`, `typer` |
| Container | `ghcr.io/osgeo/gdal:ubuntu-small-3.12.2` + `uv`, `postgresql-client`, `jq` |
| Database | `postgis/postgis:17-3.5` |
| Volumes | `/data/incoming` (ro), `/data/outgoing` (rw), `/data/work` (rw) |
| Tests | `tests/test_ingest_vector.py` — one test, asserts `PROMOTE_TO_MULTI` in an ogr2ogr argv |
| Export formats | GPKG, GeoJSON (`llm_gis/exporter.py`) |

Pieces of the original's target architecture that already exist in embryo and should be
grown rather than replaced:

- `llm_gis/inspect.py:inspect_dataset` already emits a dataset descriptor:
  `dataset_kind`, `detected_crs`, `extent`, `crs_status`, `crs_reasons`. This is the seed
  of O1's `DatasetDescriptor`.
- `llm_gis/common.py:crs_status` already performs deterministic CRS plausibility checks
  (lon/lat extent vs projected CRS, and the reverse). This is the seed of O9's QC.
- `llm_gis/common.py:make_ingest_id` / `sha256_for_path` already give content-addressed
  provenance identifiers, reusable as cache keys (O12).

---

## 2. Departures from the original, with rationale

**D1 — Do not build the `DataSource` / `Asset` abstraction first (changes O1, O19 Phase A).**
The original specifies a twelve-attribute `Asset` including "candidate execution engines"
before any non-local source exists. That interface would be designed from imagination
against a 970-line codebase. Instead: implement DuckDB (Phase 2) and STAC (Phase 4)
concretely, each carrying its own small descriptor, then extract the shared abstraction in
Phase 5 from two real implementations. Until then the rule is only "do not make extraction
harder": new code takes a descriptor dict, not a file path, where that is free.

**D2 — DuckDB before STAC (swaps O2 and O3).** DuckDB spatial on GeoParquet has no
dependency on O1 or O2, is the single largest capability gain, and is independently useful
the day it lands. STAC discovery is only valuable once there is a non-PostGIS path to feed.

**D3 — A regression harness is a prerequisite, not Phase F.** The original's Example 1
("no regression" on the local GeoPackage path) is unverifiable today: one unit test exists
and it tests argv construction. Phase 0 establishes the baseline before anything moves.

**D4 — Defer the engine capability registry (O14).** A registry describing two engines is a
lookup table wearing architecture's clothes. Revisit when a fourth engine lands.

**D5 — The execution planner (O4) follows the engines, not the reverse.** Planner rules
written before both engines are in real use are guesses with a `reason` string attached.
Phase 6, after Phases 2 and 4 have produced actual decisions worth encoding.

**D6 — Container and dependency plumbing is explicit work, not a footnote.** Every `bin/*`
command runs inside the compose `agent` service. Remote asset access needs egress from
that container, GDAL `/vsicurl` configuration, DuckDB `httpfs`, a writable cache location,
and credential passing. The original does not mention this and it is the first thing that
will break. Folded into Phase 2 as a first-class deliverable.

**D7 — Promote QC and preview (O9, O8) above the SDI adapters (O7).** They serve the
operator model in `CLAUDE.md` directly — the agent checking its own output — and each is
small and independent. The OGC/ArcGIS/WFS adapter family is large and should wait for
concrete demand from a real job.

**D8 — no `rasterio`.** The plan specifies `uv add rasterio`. The image's own GDAL 3.13.3
performs every Phase 7 capability, measured on 2026-09-10 and tabulated in the Phase 7
design: remote inspect, overview-based approximate statistics without a full download,
windowed read and COG export writing 478 KB from a 150 MB scene, exact statistics on the
window, zonal statistics straight against the remote COG with values identical to a local
clip, and PNG rendering. A PyPI `rasterio` wheel would put a second GDAL and PROJ stack
beside the image's, to be kept in step, and would buy none of it. Exposing the image's
`osgeo` bindings into the venv through system site packages avoids the double stack but
breaks the venv's isolation and buys none of it either.

**D9 — accepted risk on the provisional `gdal` CLI.** `gdal raster zonal-stats` belongs to
GDAL's unified command line interface, which prints that it is "provisionally provided" and
that the project "reserves the right to modify, rename, reorganize, and change the behavior
of the utility until it is officially frozen in a future feature release". We pin
`ghcr.io/osgeo/gdal:ubuntu-small-3.13.3` exactly, so nothing moves underneath us. The
exposure is one command, and a future image bump must re-verify it. Everything else in
Phase 7 uses the frozen classic utilities.

---

## 3. Constraints that apply to every phase

- Package manager is `uv`. `uv add <pkg>`, `uv run <cmd>`. Never `pip`, never `python3`.
- New runtime dependencies must work in `ghcr.io/osgeo/gdal:ubuntu-small-3.12.2` and be
  added to `pyproject.toml`; the host `uv` environment is also used for quick GeoPandas /
  `ogrinfo` checks per `CLAUDE.md`, so anything needed host-side must install there too.
- `data/incoming/` stays read-only. Produced files go to `data/outgoing/<YYYY-MM-DD>_<project>/`.
- Cached and intermediate artefacts go under `/data/work/` (already a rw mount); add
  `/data/work/cache/` via `ensure_workspace_dirs`.
- Existing command names, flags and JSON field names keep working. Additive changes only.
- No emojis in code. Short modules, short functions, docstrings over inline comments.
- Tests must pass with no network. Live-service tests live in `tests/live/` and are excluded
  from the default run.

---

## 4. Phases

Each phase ends with something usable. Phases are ordered; within a phase, steps are.

**Every phase ends with a field test before it counts as done.** A field test is a
real job run end to end through the `bin/*` commands, as the operator described in
`CLAUDE.md`, on real data rather than fixtures. Passing tests and green CI prove the
code runs; only a field test shows whether the workflow holds for someone trying to
get work done. Findings go in `docs/reports/` and feed the next phase.

Phase 0's field test ran the activation KML through inspect, stage, ingest, SQL and
export. The chain worked and the numbers verified, and it surfaced four things the
suite could not: stage and ingest write to the same report path so staging
provenance is overwritten; no step reports what it produced, so a caller cannot tell
a step worked without re-inspecting; absent JSON keys return null rather than
erroring, which reads identically to a genuine null; and the job it was meant to do
needs STAC and windowed COG access, which do not exist yet. The first three are
Phase 1 and Phase 3 work; the fourth is the wall this plan exists to remove.

Two operational notes from that run. `docker compose down -v` destroys the `pgdata`
volume along with everything else: remove a single named volume by name instead.
And `CLAUDE.md` describes archiving sources to `data/archive/`, but no such directory
exists or is mounted, so the archive step has nowhere to write.

### Phase 0 — Regression baseline

**Why:** nothing below is safe to attempt without it.

**Deliverables**
- `tests/fixtures/` — one small GeoPackage (a handful of polygons, EPSG:4326) and one
  small GeoTIFF, both committed, both a few KB.
- `tests/test_inspect.py` — `inspect_dataset` on both fixtures returns the expected
  `dataset_kind`, `detected_crs`, `extent` and `crs_status: ok`.
- `tests/test_crs_status.py` — table-driven tests over `common.crs_status`: missing CRS,
  EPSG:4326 with a metre-scale extent, UTM with a lon/lat-scale extent, and the ok case.
- `tests/live/test_postgis_roundtrip.py` — stage, ingest-vector, run a trivial SQL, export
  to GPKG, assert feature count survives. Requires the compose stack; excluded by default.
- `pyproject.toml` — pytest config with a `live` marker deselected by default, and
  `uv add --dev pytest`.
- `bin/test` — `docker compose run --rm agent uv run pytest`, matching the `bin/*` idiom.

**Done when:** `uv run pytest` passes on the host with no database, and
`bin/test -m live` passes with the stack up.

### Phase 1 — Agent-oriented CLI contract

**Why:** cheap, and it constrains the shape of every command added afterwards. Doing it
after ten more commands exist costs ten times as much.

**Deliverables**
- `llm_gis/errors.py` — a `GisError` exception carrying `code`, `message`,
  `suggested_action`, and a Typer exception handler in `cli.py` that renders it as JSON on
  stderr and exits non-zero. First codes: `INPUT_NOT_FOUND`, `CRS_MISSING`,
  `CRS_SUSPICIOUS`, `UNSUPPORTED_FORMAT`, `COMMAND_FAILED`.
- `common.run_command` raises `GisError(code="COMMAND_FAILED")` with the failing argv and
  stderr in structured fields rather than one interpolated string.
- Audit of all 9 commands: JSON result on stdout and nothing else; diagnostics on stderr;
  exit 0 on success, 1 on handled error, 2 on usage error.
- `tests/test_errors.py` — invoking a command against a missing path yields exit 1, clean
  JSON on stdout-or-stderr as specified, and the right `code`.

**Done when:** every command's stdout parses as JSON on both success and failure paths.

### Phase 2 — DuckDB spatial execution path

**Why:** the largest capability gain in the plan, and it unblocks Phases 4 and 6.

**Deliverables**
- `uv add duckdb`; `INSTALL spatial; LOAD spatial;` and `INSTALL httpfs; LOAD httpfs;`
  handled in a small connection factory, extensions cached under `/data/work/cache/duckdb/`
  so repeated container runs do not re-download them.
- `llm_gis/duck.py` — connection factory plus a `describe(uri)` returning schema, row
  count, geometry column, CRS where GeoParquet metadata carries it, and bbox.
- `llm_gis/query.py` — a bbox-and-attribute filter executed against a Parquet/GeoParquet
  URI, returning either a summary or a materialised output file. Higher-level and
  deterministic; raw SQL stays a separate, explicitly privileged command (see O3's security
  note — `run-sql` already occupies that role for PostGIS).
- New commands `bin/duck-describe` and `bin/duck-query` following the existing wrapper idiom.
- `llm_gis/exporter.py` gains GeoParquet output (`-f Parquet`), so results can stay
  cloud-native.
- Container work: confirm egress from the `agent` service, set `GDAL_HTTP_*` and
  `AWS_*`/S3 endpoint passthrough in `docker-compose.yml` where needed, add the cache dir
  to `ensure_workspace_dirs`.
- Tests: local GeoParquet fixture through describe and query, no network. One
  `tests/live/` test against a public remote GeoParquet URL.

**Done when:** a bbox query against a remote GeoParquet returns a small result without any
PostGIS involvement, and the local test suite covers describe/query offline.

### Phase 3 — Deterministic QC (O9)

**Why:** independent of everything else, high value per line, extends `crs_status` which
already exists.

**Deliverables**
- `llm_gis/qc.py` — vector metrics (feature count, geometry types, empty and invalid
  counts, bbox, CRS, area/length stats, null key attributes, duplicate IDs, unexpected Z/M)
  and raster metrics (dimensions, bands, CRS, resolution, bbox, nodata, min/max/mean,
  percent nodata).
- Structured warnings in the shape the original specifies: `{status, warnings: [{code,
  message, severity}]}`, with `GEOGRAPHIC_CRS_FOR_METRIC_OPERATION`,
  `EMPTY_RESULT_UNEXPECTED`, `RESULT_BBOX_DISJOINT_FROM_INPUT` as the first checks.
- `bin/qc <dataset-or-table>`; QC block attached to `export` output.

**Done when:** QC runs over both a file and a PostGIS table and its warning codes are
covered by fixture tests.

### Phase 4 — STAC discovery (O2)

**Deliverables**
- `uv add pystac-client`.
- `llm_gis/catalog.py` — registered endpoints in `/data/work/catalogs.json`; conformance
  and collection listing; item search by bbox, datetime and collection; asset listing.
- Commands: `bin/catalog-add`, `bin/catalog-collections`, `bin/catalog-search`,
  `bin/catalog-item`, `bin/catalog-assets`.
- Discovery never downloads. Asset listing emits href, media type, roles and size where
  advertised, so Phase 2's query path can consume a GeoParquet asset href directly.
- Tests: recorded JSON fixtures for search, item and asset parsing, plus malformed and
  unreachable catalogue cases. One `tests/live/` smoke test against a public endpoint.

**Done when:** the original's Example 2 runs end to end — public STAC, discover a remote
GeoParquet asset, DuckDB bbox query, result written — with no ingestion.

### Phase 5 — Extract the asset abstraction (O1, deferred here by D1)

**Why now:** two independent producers of dataset descriptions exist (Phase 2 `describe`,
Phase 4 asset listing) plus the pre-existing `inspect`. The common shape is now observed
rather than imagined.

**Deliverables**
- `llm_gis/asset.py` — one dataclass or Pydantic model unifying what those three actually
  emit. Fields are admitted only if a current caller populates them.
- `inspect`, `duck-describe` and `catalog-assets` all return it; existing JSON field names
  preserved as a compatibility surface.
- Provenance carried on the asset: source URI, source type, catalogue and item id where
  applicable, retrieval timestamp, hash where local.

**Done when:** all three commands emit the same descriptor shape and the Phase 0 tests
still pass unchanged.

### Phase 6 — Execution strategy layer (O4, O10)

**Deliverables**
- `llm_gis/planner.py` — a small rule table over (format, local/remote, size, operation,
  persistence needed) returning `{strategy, reason, fallback}`. Conservative and readable;
  no optimiser.
- `bin/plan <operation> ...` emitting the serial step list the original sketches in O10.
- `--engine duckdb|postgis` and `--materialise/--no-materialise` overrides on the
  operations that have two viable routes.
- Tests: rule table cases asserted directly; overrides win over rules.

**Done when:** the planner explains, in one machine-readable object, why a route was chosen
for each of the Phase 2 and Phase 4 workflows.

### Phase 7 — Cloud raster (O6) and preview (O8)

- COG inspection and windowed AOI reads via `rasterio` (`uv add rasterio`), reprojection,
  statistics, clipping, zonal stats; materialise only when required; COG export.
- `bin/preview <dataset>` producing a deterministic PNG plus bbox, CRS, render parameters
  and a feature/raster summary, so a vision-capable model can spot swapped coordinates,
  empty intersections or features far from the AOI. Library-based rendering only; no tile
  server dependency.

**Done when:** the original's Example 3 runs — STAC, COG, remote inspect, AOI window read,
statistics, derived output — without downloading the full raster.

---

## 5. Feature classification against the original

Status as of 2026-09-11, after an end-to-end run of Examples 1-4 confirmed the merged
phases hold together (`docs/reports/2026-09-11_examples-1-4-verification.md`). Dates below
are each phase's merge commit date on `main`.

| Original section | Classification | Note |
|---|---|---|
| O1 Asset abstraction | MERGED, Phase 5 (2026-09-08) | Extracted from working code, not designed up front (D1). |
| O2 STAC | MERGED, Phase 4 (2026-09-07) | Generic `pystac-client`, fixtures over live calls; also field-tested live (`docs/reports/2026-09-07_phase4-stac-field-test.md`). |
| O3 DuckDB + spatial | MERGED, Phase 2 (2026-09-07) | Promoted to first capability phase (D2). |
| O4 Execution planner | MERGED, Phase 6 (2026-09-10) | Needs two live engines first (D5); field-tested (`docs/reports/2026-09-10_phase6_field_test.md`). |
| O5 Portolan | DEFERRED | Revisit after Phase 4 proves generic STAC against a Portolan catalogue. No Portolan-specific code until a generic path demonstrably fails. Still blocked on a concrete Portolan catalogue endpoint — no alias configured and Example 5 could not be run for want of one. |
| O6 COG-first raster | MERGED, Phase 7 (2026-09-11) | GDAL reads a remote COG through `/vsicurl`; PostGIS raster retained, no longer the default sink (D8). |
| O7 OGC / ArcGIS / WFS adapters | DEFERRED | Large surface, no current job requires it (D7). Revisit on demand, one protocol at a time. |
| O8 Preview | MERGED, Phase 7 (2026-09-11) | `bin/preview` renders a deterministic PNG with AOI outline and graticule; library rendering only, no server. Intermediate-file gap fixed 2026-09-14: GDAL intermediates (`.red.tif`, `.green.tif`, `.blue.tif`, `.rgb.vrt`, `.data.geojson`, `.graticule.geojson`) render in a temp dir under `work_root()/tmp/` and are removed after each run; the `.png.aux.xml` PAM sidecar GDAL wrote next to the final PNG is now suppressed with `--config GDAL_PAM_ENABLED NO` on the `gdal_translate` PNG write. An `--output` under `data/outgoing/` now leaves only the PNG and its `.preview.json` sidecar. |
| O9 QC | MERGED, Phase 3 (2026-09-07) | Promoted; extends existing `crs_status`; field-tested (`docs/reports/2026-09-07_phase3-qc-field-test.md`). |
| O10 Operation plans | MERGED, Phase 6 (2026-09-10) | Serial plan, no DAG engine. |
| O11 Provenance | PARTIAL, Phase 5 (2026-09-08) | `analysis.json` manifest follows the asset model; ingest ids and hashes already exist. |
| O12 Cache | PARTIAL, Phase 2 (2026-09-07) | Filesystem cache under `/data/work/cache/`, keyed on source URI plus query. Full inspect/clear commands deferred. |
| O13 Agent-oriented CLI | MERGED, Phase 1 (2026-09-05) | Promoted; constrains all later commands. |
| O14 Capability registry | REJECTED for now | Two engines do not need a registry (D4). |
| O15 Modern output formats | PARTIAL, Phase 2 (2026-09-07) | GeoParquet added alongside GPKG/GeoJSON; PMTiles/COPC/GeoZarr deferred. |
| O16 OGC API Processes | DEFERRED | Explicitly last in the original; unchanged. |
| O17 MCP interface | DEFERRED | Revisit once the execution model is stable. The CLI stays primary. |
| O20 Demonstration workflows | Examples 1-4 MERGED/VERIFIED; Example 5 DEFERRED | Example 1 (local GPKG round trip), Example 2 (Overture STAC to GeoParquet, DuckDB bbox filter, no ingestion) and Example 3 (STAC to COG, remote inspect, AOI window read, statistics) all ran clean end to end on 2026-09-11, alongside a first live run of Example 4 (two remote Overture themes, DuckDB subset via `--format geopackage`, PostGIS reprojection and spatial join, QC, preview, GeoPackage export). Example 5 (Portolan) is blocked on O5. See `docs/reports/2026-09-11_examples-1-4-verification.md`. |
| O21 Testing | ACTIVE, Phase 0 onward | 29 test modules, 6 of them under `tests/live/` and excluded from the default run so an offline catalogue never fails the suite. |
| O22 Documentation | ACTIVE, per phase | Each phase updates `README.md`, `AGENTS.md` and `.claude/skills/hot-start/SKILL.md` with the commands it adds and the engine-choice guidance (GDAL / DuckDB / PostGIS / Rasterio) as defaults rather than rules. Documentation ships with the phase, not after it. |
| O25 Decision log | ACTIVE | This document's "Departures" section (D1-D9) is the decision log; new decisions append there with their rationale. |

---

## 6. Housekeeping before starting

`main` currently carries 8 modified tracked files and a large untracked set (`.claude/`,
`.codex/`, `tests/`, several `docs/plans` and `docs/reports` entries). Land or branch these
before Phase 0, so the regression baseline is measured against a known tree.

## 7. Open questions

1. Is there a concrete near-term job that needs OGC API - Features or ArcGIS REST? If yes,
   O7 moves up; if no, it stays deferred.
2. Which public STAC endpoint should the live smoke test target — and is a Portolan
   catalogue available to test the generic path against (Phase 4 / O5)?
3. Should `run-sql` gain a DuckDB counterpart, or does `duck-query` plus PostGIS `run-sql`
   cover the need? Adding raw DuckDB SQL widens the privileged surface.
