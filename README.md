# llm-gis

`llm-gis` is a headless GIS workspace you run with Docker. Drop geospatial
files into `data/incoming/`, run a few commands, and get analysis results
back in `data/outgoing/`.

This project is for:
- loading vector and raster data into PostGIS
- checking CRS information before import
- running repeatable spatial SQL, including ad hoc querying of cloud-native
  formats without loading them first
- discovering datasets in STAC catalogues
- exporting results as GeoPackage, GeoJSON, or GeoParquet

This project is not a web map, a desktop GIS, or a notebook environment.

## Use from another folder

On Linux with local Docker and uv, install the host launcher and global skills:

```bash
uv run --script scripts/install-global.py --check
# Review the proposed changes before replacing existing personal skills.
uv run --script scripts/install-global.py --replace
```

Start Codex or Claude in your data folder and ask an analytical question. The
skill uses the global launcher, returns query values in chat, and saves requested
artifacts in your chosen folder (default `./results/`). Existing files are refused.
The CLI equivalent is `~/.local/bin/llm-gis inspect parcels.gpkg` from that folder.
See [the global workflow](docs/llm/GLOBAL_WORKFLOW.md) for path restrictions,
query limits and retained job files. Legacy repository wrappers remain available.

## Architecture

| Layer | Tool | Role |
|-------|------|------|
| Persistent storage | PostGIS | System of record for ingested vector/raster tables and ingest metadata (`meta.ingestions`) |
| Ephemeral querying | DuckDB | Filters and reads cloud-native formats (Parquet/GeoParquet, remote COGs) in place, no load step required |
| Raster I/O | GDAL (`ogrinfo`, `gdalinfo`, `gdalwarp`, `/vsicurl`) | Inspection, reprojection, and windowed reads of local or remote rasters |
| Discovery | STAC (`pystac-client`) | Finds datasets and assets in STAC catalogues by area/time before anything is downloaded |

An execution planner (`bin/plan`) sits on top and decides, per operation,
whether DuckDB or PostGIS should run it — see
[`docs/superpowers/specs/2026-09-10-execution-planner-design.md`](docs/superpowers/specs/2026-09-10-execution-planner-design.md).

## What You Need

- Docker
- Docker Compose v2
- Bash (Linux, macOS, or WSL on Windows)

Docker provides PostgreSQL, PostGIS, GDAL, and Python. Run legacy `bin/<command>`
wrappers from the repo root. The optional global launcher also needs host uv and
runs from the caller's data folder.

## 5-Minute Setup

```bash
git clone <repo-url>
cd llm-gis
docker compose up -d --build
bin/inspect data/incoming/<some-file>
```

`docker compose up` starts two services, `db` and `agent`. `bin/inspect`
should return JSON describing the file's format and CRS — that confirms the
stack is working. If it fails, run `bin/doctor` and fix Docker before trying
anything else.

`bin/*` commands run the container as your own user, so files written to
`data/outgoing/` and `data/work/` belong to you, not root.

## Project Folders

| Folder | Purpose |
|--------|---------|
| `data/incoming/` | Put raw input files here (read-only during processing) |
| `data/work/` | Temporary files, logs, and SQL working files |
| `data/outgoing/` | Exported results, in dated subfolders |
| `data/archive/` | Processed source files, moved here after a workflow completes |

## The Normal Workflow

1. Put a dataset in `data/incoming/`
2. `bin/inspect` it to check CRS and metadata
3. `bin/ingest-vector` or `bin/ingest-raster` it into PostGIS
4. `bin/run-sql` a spatial analysis
5. `bin/export` the result to `data/outgoing/`

PostGIS extensions and metadata tables are created automatically on first
startup — nothing to prepare by hand.

## Common Commands

| Command | Use it for |
|---------|------------|
| `bin/doctor` | Check Docker, the database, and GIS tools are reachable |
| `bin/inspect <path>` | Read dataset metadata and CRS status before import |
| `bin/ingest-vector <path> --table <name>` | Load vector data into PostGIS |
| `bin/ingest-raster <path> --table <name>` | Load raster data into PostGIS |
| `bin/describe-table <schema.table>` | Check what was loaded or created |
| `bin/run-sql <file> --ingest-id <id>` | Run a spatial SQL workflow against PostGIS |
| `bin/duck-query <uri> [--bbox] [--where] [--output]` | Filter a Parquet/GeoParquet source in place with DuckDB, no ingest needed |
| `bin/plan <operation> <uri>` | Show which engine (DuckDB or PostGIS) would run an operation, and why |
| `bin/export <path> --format gpkg\|geojson --table <schema.table>` | Write a result file |
| `bin/qc <path-or-table>` | Deterministic metrics and warnings for a dataset or table |
| `bin/list-ingestions` | Review earlier ingests |
| `bin/catalog-search <catalog> [--bbox] [--datetime]` | Find STAC items by area and time |
| `bin/catalog-assets <item-url>` | Asset hrefs and what can read them |
| `bin/raster-window <path-or-url> --bbox <box>` | Read an AOI out of a raster (local or remote COG) without downloading it |
| `bin/preview <path-or-url> [--aoi <vector>]` | Render a dataset to a deterministic PNG with an AOI outline |

Every command prints JSON. If CRS status is `missing` or `suspicious`,
re-ingest with `--src-crs EPSG:XXXX` rather than trusting the auto-detected
value.

## Roadmap

All 7 phases are merged to `main`. Each phase's design and rationale live in
`docs/superpowers/specs/`:

| Phase | Delivered | Spec |
|-------|-----------|------|
| 0 — Regression baseline | Test harness before any change | — |
| 1 — Agent-oriented CLI contract | JSON-only, non-interactive `bin/*` commands | [guided-cli-experience](docs/superpowers/specs/2026-03-30-guided-cli-experience-design.md) |
| 2 — DuckDB spatial execution path | Query Parquet/GeoParquet and remote data without loading it first | — |
| 3 — Deterministic QC | `bin/qc` metrics and warnings on exports | [deterministic-qc](docs/superpowers/specs/2026-09-07-deterministic-qc-design.md) |
| 4 — STAC discovery | `bin/catalog-*` commands against STAC catalogues | [stac-discovery](docs/superpowers/specs/2026-09-07-stac-discovery-design.md) |
| 5 — Asset abstraction | Common dataset-descriptor shape across `inspect`/`describe`/catalog | [asset-abstraction](docs/superpowers/specs/2026-09-07-asset-abstraction-design.md) |
| 6 — Execution strategy layer | `bin/plan` chooses DuckDB vs. PostGIS per operation | [execution-planner](docs/superpowers/specs/2026-09-10-execution-planner-design.md) |
| 7 — Cloud raster and preview | `bin/raster-window`, `bin/preview`; GDAL reads remote COGs via `/vsicurl` | [cloud-raster-and-preview](docs/superpowers/specs/2026-09-10-cloud-raster-and-preview-design.md) |

Full status detail and feature-by-feature tracking:
[`docs/plans/2026-09-04_improvement_plan_revised.md`](docs/plans/2026-09-04_improvement_plan_revised.md).

## Running The Tests

```bash
bin/test              # offline suite, no database needed
bin/test -m live      # full workflow against PostGIS; needs `docker compose up -d db`
```

`bin/test` runs inside the container, using the same GDAL the workflow uses,
and is the one that counts in CI. `uv run pytest` on the host works for the
offline suite too, but a different host GDAL version can report slightly
different metadata.

## Where To Find More

This README is the operator's entry point. For deeper detail:

- [`AGENTS.md`](AGENTS.md) — how agents should operate this workspace
- [`docs/llm/README.md`](docs/llm/README.md) — full command reference and canonical paths
- [`docs/llm/QUICKSTART.md`](docs/llm/QUICKSTART.md) — worked examples
- [`docs/llm/OUTPUT_SCHEMA.md`](docs/llm/OUTPUT_SCHEMA.md) — every command's exact JSON keys and error envelope
- [`docs/superpowers/specs/`](docs/superpowers/specs/) — design rationale for each roadmap phase
- [`docs/plans/2026-09-04_improvement_plan_revised.md`](docs/plans/2026-09-04_improvement_plan_revised.md) — roadmap status in full
