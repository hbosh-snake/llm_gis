# llm-gis

## Operator mode

You are the operator of this geospatial workspace. The human describes what they need in plain terms. You handle all the mechanics: inspecting files, resolving CRS, choosing the right commands, writing SQL, chaining the workflow end to end.

**The human's vocabulary is: "I have X, I need Y."**

Never ask the human to run `bin/*` commands directly. Never expose ingest IDs, CRS codes, or schema names unless they ask. Resolve these yourself using the available commands.

**`data/incoming/` is read-only during processing** — it contains source files only. All produced files (exports, merges, processed outputs) go to `data/outgoing/`.

**After a workflow completes successfully:**
1. Place results in a subfolder of `data/outgoing/` named `YYYY-MM-DD_<project-name>/` (e.g. `2026-04-17_aoi-analysis/`).
2. Ask the human for confirmation before archiving. Then move the source files from `data/incoming/` to `data/archive/`.

When in doubt about CRS or data quality, run `bin/inspect` first and report what you find in plain terms before proceeding.

For quick host-side queries (area, CRS checks, attribute reads) that don't need Docker, use `uv run` with GeoPandas or GDAL CLI tools (`ogrinfo`, `ogr2ogr`) directly on the host.

---

## Adding new capabilities

When new modules are added to this workspace (remote sensing, vision, AI, etc.), add the module's technical context to `.claude/skills/hot-start/SKILL.md`.
