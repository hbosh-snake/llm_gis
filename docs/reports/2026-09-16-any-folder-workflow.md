# Any-folder workflow acceptance — 2026-09-16

The first-version CLI acceptance cases pass. Fresh Codex and Claude CLI sessions
also selected the installed skill without its name in the prompt, answered from
query results, and delivered the requested clipped file. This verifies the local
Linux/Docker installation; it does not test graphical clients or other hosts.

## Scope

Implementation: 6d9ab11. Follow-up fixes: eb79508 (persistent uv-managed Python)
and 8640a88 (test job isolation). This acceptance change adds one live host test
file and updates delivery notes. No backend behavior, dependencies, architecture,
installed skills, or deferred features were changed.

## Automated evidence

| Command | Result |
|---|---|
| `bin/doctor` | Database OK; GDAL 3.13.3; psql 18.6 |
| `bin/test` | 235 passed, 31 live tests deselected |
| `uv run pytest tests/host -q` | 43 passed, 5 live tests deselected |
| `uv run pytest tests/host -m live -q` | 5 passed, 43 deselected |
| `bin/test -m live tests/test_query_sql.py` | 14 passed, 10 deselected |
| `uv run pytest tests/host/test_any_folder_live.py -m live -q` | 3 passed after adding exact clipped-geometry comparisons |

The three new cases use generated sources in an external folder with spaces and
a second input folder. An unrelated `pyproject.toml` requiring Python >=99 checks
that the caller's project does not replace the backend environment.

- Count and area: 12 rectangles in EPSG:3035, with independently known areas
  100–1,200 m²; total 7,800 m². No artifact is created for these query answers.
- Ranking: the ten largest parcels are 12 through 3, with areas 1,200 through
  300 m², in deterministic order.
- Clip/export: the boundary halves every rectangle. Independent GeoPandas reads
  verify every geometry, parcel identifier, EPSG:3035, output ownership and the
  absolute requested output path. Export QC has no warnings.
- Concurrency: two ingests of the same source produce different IDs/schemas and
  correct distinct exports. Concurrent raster reads use separate VRT workspaces,
  return the fixture's mean of 1,200 and write matching rasters to distinct paths.
- Source hashes remain unchanged; per-call temporary directories are removed.
  Tests use temporary job roots and remove their own successful test ingestions.

Existing tests cover output refusal, prohibited/conflicting mounts, missing Docker,
malformed and multi-statement SQL, read-only enforcement, timeouts, and complete
CSV/JSON export beyond preview caps. The unrelated network-backed live suite was
not rerun; the acceptance run uses local fixtures and PostGIS.

## Fresh client checks

Each client started a new session in its own external fixture folder, with this
request and no skill name:

> How many polygons are in parcels.gpkg and what is their total area in square
> metres? Show the ten largest parcels. Clip parcels.gpkg to boundary.gpkg and
> save results/clipped.gpkg.

Both clients returned 12 polygons, 7,800 m² and the correct ten-row ranking. Both
linked the requested `results/clipped.gpkg`. An independent host read verified
12 features, 3,900 m², EPSG:3035 and all expected clipped geometries. Source hashes
still matched the ingest reports, and artifacts belonged to the invoking user.

Two recoveries matter when interpreting this result:

- Claude first tried a bare `llm-gis` command whose PATH resolution was unsuitable
  outside the repository. It recovered using the installed launcher's absolute
  path, as the skill directs. No shell settings were changed.
- Codex's initial CTE-based SQL export produced missing CRS metadata; QC reported
  `CRS_MISSING`. Adding a cast to that query did not resolve it. Codex materialized
  a typed analysis table and exported it with `--table`, then replaced only its
  own failed fixture output with the verified result. The final requested file
  has EPSG:3035 and no QC warnings. This was a successful recovery, not a clean
  first-attempt export; explicit CRS verification remains necessary.

Local transcripts, command evidence and independent verification are retained
under `data/work/acceptance-2026-09-16/` (ignored by Git). Its `client-root.txt`
records the disposable external fixture location. The report records the durable
outcomes; temporary fixture files are not release artifacts.

## Handoff

Installed launcher: `~/.local/bin/llm-gis`. Installed skills:
`~/.codex/skills/llm-gis/SKILL.md` and `~/.claude/skills/llm-gis/SKILL.md`.
The global workflow remains documented in `docs/llm/GLOBAL_WORKFLOW.md`.

Existing deferrals remain unchanged: whole-job cleanup, locking explicit ingest
IDs, same-destination write races, additional DuckDB/raster row previews, and
other platforms. The first-version acceptance work does not expand these limits.
