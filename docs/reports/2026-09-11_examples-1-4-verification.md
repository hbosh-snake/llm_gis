# Examples 1-4 verification, all phases merged - 2026-09-11

## Scope

All 7 phases (0-7) are now on `main`. Ran the original plan's worked examples 1-4
(`docs/plans/2026-09-04_improvement_plan.md` §20) end to end through `bin/*` to confirm
the merged system still hangs together, using `docker compose up -d db` (no build
needed). Example 5 (Portolan) could not be run; see below.

- Environment: `bin/doctor` reported `database_ok: true`, GDAL 3.13.3, psql 18.6.
- Network: the agent container reached `stac.overturemaps.org`,
  `overturemaps-us-west-2.s3.us-west-2.amazonaws.com`, `earth-search.aws.element84.com`
  and `sentinel-cogs.s3.us-west-2.amazonaws.com` directly.

## Example 1 - local GeoPackage round trip

`local GeoPackage -> inspect -> PostGIS -> spatial analysis -> GeoPackage`

Used `tests/fixtures/aoi.gpkg` (4 polygons, EPSG:4326). `inspect` reported `crs_status:
ok`. `ingest-vector --dst-crs EPSG:3035` loaded 4 features with 0 invalid geometries.
Ran a buffer + area SQL analysis, then `export --format gpkg --compare-to ...
--expect-non-empty`: all 5 QC checks passed, no warnings.

**Result: clean pass, no regression.**

## Example 2 - remote GeoParquet

`STAC -> find dataset -> remote GeoParquet -> DuckDB bbox filter -> aggregate/query -> GeoParquet result`

`catalog-search overture --collection building --bbox 10.0,45.0,10.3,45.3` found item
`00204` (4,919,778 rows in its part file). `catalog-assets` returned the S3/Azure
GeoParquet hrefs. `duck-query --bbox 10.0,45.0,10.3,45.3 --output
verify_ex2_buildings.parquet` matched 48,581 of 4,919,778 rows and materialised only the
subset. `bin/qc` on the result: 48,581 features, 0 invalid, all checks pass.

**Result: clean pass. No full dataset ingestion; PostGIS never touched.**

## Example 3 - cloud raster

`STAC -> COG -> inspect remotely -> AOI window read -> calculate statistics -> derived output`

`catalog-search earth-search --collection sentinel-2-l2a --bbox 8.90,45.95,8.96,46.00`
found `S2A_32TMR_20260909_0_L2A`. `catalog-assets` returned the B04 COG href (also an S3
JP2 fallback). `bin/inspect` on the remote COG returned header metadata only (10980x10980,
EPSG:32632) - no pixels read. `bin/raster-window --bbox ... --bbox-crs EPSG:4326 --output
verify_ex3_window.tif` read the AOI window, returned band statistics (min 8740, max 12168,
mean 10738.5) and wrote a 374 KB derived GeoTIFF window - no full-scene download.

**Result: clean pass.**

## Example 4 - complex multi-dataset GIS

`remote dataset A + remote dataset B -> subset both -> materialise -> PostGIS -> reprojection + spatial join -> QC -> preview -> GeoPackage`

First live run of this chain (no prior field test). Subsetted two Overture themes over a
0.1x0.1 degree AOI (10.10,45.05,10.20,45.15): `building` (3,645 features) and `land_use`
(345 features), both via `duck-query --bbox ... --format geopackage` so the subset lands
as a file the agent image's GDAL can read (see finding 1 below). Ingested both into
PostGIS reprojected to EPSG:3035, spatial-joined buildings to land-use polygons
(`ST_Intersects`), QC'd and exported the 3,364-row join result, then rendered a preview
PNG.

**Result: pass, after two fixes made during the run (see findings 1 and 2). Both are
operator-usage issues, not defects in the merged code.**

### Finding 1 - GeoParquet needs the DuckDB->GeoPackage bridge before PostGIS ingest

The agent image's GDAL build has no Parquet driver (`ogrinfo --formats` lists none), so
`bin/inspect` and `bin/ingest-vector` cannot read a `duck-query --output foo.parquet`
file directly - `ingest-vector` shells to `ogr2ogr`, which fails with `UNSUPPORTED_FORMAT`.
This is by design and documented in `llm_gis/query.py`'s docstring: `duck-query --format
geopackage` writes through DuckDB's own bundled GDAL for exactly this reason, and it is
the path `bin/plan` recommends for a Parquet source that needs `--materialise`. Not a
gap - flagging because it is easy to miss on a first pass (the initial `--output
*.parquet` calls had to be redone with `--format geopackage`), and a one-line pointer
from `ingest-vector`'s `UNSUPPORTED_FORMAT` error to `duck-query --format geopackage`
would save the detour.

### Finding 2 - a spatial join can produce duplicate fids for GPKG export

`SELECT b.fid, ... FROM buildings b JOIN land_use lu ON ST_Intersects(...)` reused the
source table's `fid` after a join that can match one building to more than one land-use
polygon. `ogr2ogr -f GPKG` treats `fid` as the primary key, so `export` failed with
`UNIQUE constraint failed: ...fid`. Fixed by generating a fresh id with `ROW_NUMBER() OVER
()` instead of carrying the pre-join `fid` through a fan-out join. This is a SQL-authoring
mistake in this verification run, not a system defect, but worth remembering: any table
that will be exported to GPKG needs a genuinely unique `fid`, and a join is the most
common way to lose that property silently (`run-sql` reported the table as created; only
`export`'s `ogr2ogr` step caught the collision).

### Finding 3 - `bin/preview --output` drops intermediates next to the deliverable

`bin/preview ... --output /data/outgoing/verify_ex4_preview` produced the expected
`verify_ex4_preview.png` and `verify_ex4_preview.preview.json`, but also left
`.red.tif`, `.green.tif`, `.blue.tif`, `.rgb.vrt`, `.data.geojson`,
`.graticule.geojson` and `.png.aux.xml` in the same directory. `llm_gis/preview.py` uses
`Path(output).parent` as its GDAL work directory when `--output` is given (and a real work
directory under `/data/work/preview/` only when `--output` is omitted). Operator mode
routes deliverables straight to `data/outgoing/<date>_<project>/`, so passing `--output`
there - the natural choice - pollutes that folder with seven intermediate files that need
manual cleanup. Recommend `preview` always stage intermediates in `work_root() /
"preview"` and copy only the PNG + sidecar to `--output` when given.

## Example 5 - Portolan

`Portolan catalogue -> read catalogue/agent documentation -> discover dataset through STAC -> inspect asset -> generic GeoParquet/COG path -> result`

Not run. No Portolan catalogue is configured (`bin/catalog-*`'s aliases are `overture`,
`cdse`, `earth-search`; any other catalogue needs an explicit https URL) and none is
referenced anywhere else in the repo. This matches the plan's own O5 status: DEFERRED
until a concrete Portolan endpoint exists to test the generic STAC path against. Needs a
real Portolan catalogue URL from Emanuele before this example can run - nothing to fix in
the code until then.

## Summary

| Example | Result |
|---|---|
| 1 - local round trip | Clean pass |
| 2 - remote GeoParquet | Clean pass |
| 3 - cloud raster | Clean pass |
| 4 - multi-dataset | Pass, after two in-run SQL/usage fixes (documented above) |
| 5 - Portolan | Not run - no catalogue endpoint available |

No defects found in merged code. Two documentation/UX gaps worth a small follow-up:
`ingest-vector`'s error on a raw GeoParquet input could point at `duck-query --format
geopackage`, and `bin/preview --output` should confine its intermediates to a work
directory instead of writing them next to the deliverable.
