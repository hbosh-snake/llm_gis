# llm_gis

Python package behind every `bin/*` command. `llm_gis/cli.py` is the only entry
point: it parses arguments with Typer, calls into one module per capability, and
prints a JSON envelope (`{"status": "ok", "command": ..., ...}` on success, or a
`GisError` payload on stderr with exit 1). Nothing in this package is meant to be
imported by a human at a REPL — each module is documented here for maintainers.

See the [hot-start skill](../.claude/skills/hot-start/SKILL.md) for the
workflow-level view (what a human asks for, what commands run in what order).
This file is the module-level map.

## Module index

| Module | Functional area | One-line description |
|---|---|---|
| `cli.py` | Entry point | Typer app: registers every subcommand, wraps them in a JSON success/error envelope |
| `common.py` | Shared foundation | DB connection, hashing, subprocess execution, path safety, CRS parsing — used by nearly every other module |
| `errors.py` | Shared foundation | `GisError` exception and the stable error-code vocabulary |
| `asset.py` | Shared foundation | `Asset`, the one dataset-descriptor shape `inspect`, `duck-describe` and `catalog-assets` all build and serialize from |
| `inspect.py` | Data ingestion | Measures a local or remote vector/raster source (CRS, extent, layers/bands) via ogrinfo/gdalinfo |
| `stage.py` | Data ingestion | Copies a source from `data/incoming/` into the workspace and hashes it, producing an `ingest_id` |
| `ingest_vector.py` | Data ingestion | Loads a vector file into PostGIS via `ogr2ogr`, validates and indexes geometry |
| `ingest_raster.py` | Data ingestion | Loads a raster file into PostGIS via `raster2pgsql`, with an optional `gdalwarp` reprojection first |
| `describe.py` | Data ingestion | Column names, types and row count for an already-ingested table |
| `list_ingestions.py` | Data ingestion | Recent rows from `meta.ingestions`, the ingest history log |
| `run_sql.py` | Execution | Runs an analyst-supplied `.sql` file against a PostGIS workspace with a controlled `search_path` |
| `duck.py` | Query engines | DuckDB connection and `describe`: schema, row count and extent of a Parquet/GeoParquet source, local or remote |
| `query.py` | Query engines | `duck-query`: bbox/attribute filters over a Parquet source, built to SQL and run through DuckDB |
| `raster.py` | Query engines | `raster-window`: reads an AOI out of a local or remote raster (COG) as a VRT, with band and zonal statistics |
| `catalog.py` | Query engines (discovery) | STAC catalogue discovery: collections, item search, one item, one item's assets — never downloads |
| `stac_fetch.py` | Query engines (discovery) | All network I/O behind `catalog.py`: HTTP fetch, static-catalogue traversal, search-API calls |
| `planner.py` | Execution planning | Decides which engine (duckdb/postgis/gdal) should run a job and renders the `bin/*` step list; executes nothing |
| `qc.py` | Quality control | The five deterministic QC checks and the report envelope; pure, given metrics |
| `qc_collect.py` | Quality control | All I/O behind QC: collects metrics for a file (GDAL/DuckDB) or a PostGIS table |
| `exporter.py` | Export | Writes a table or SQL query to GeoPackage/GeoJSON/GeoParquet via `ogr2ogr`, attaches a QC report by default |
| `preview.py` | Export (visual QC) | Renders a dataset + AOI to a deterministic PNG (data/AOI/graticule as RGB channels) plus a JSON sidecar |
| `doctor.py` | Diagnostics | Smoke test: tool versions, DB connectivity, workspace paths |

## Flow at a glance

```
inspect -> stage -> ingest-vector/ingest-raster -> describe-table -> run-sql -> export (+ qc)
catalog-search -> catalog-assets -> duck-query / raster-window          (no ingest, no DB)
plan                                                                     (explains the above, executes nothing)
preview                                                                  (visual QC, any stage)
```

`common.py`, `errors.py` and `asset.py` are the shared foundation every other
module sits on. `planner.py` is the only module that reasons about *which* of
the other modules to call — it imports none of their execution logic, only
`errors.py`.
