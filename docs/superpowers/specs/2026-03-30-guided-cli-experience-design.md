# Guided CLI Experience — Design Spec

**Date:** 2026-03-30
**Status:** Approved

## Problem

Opening Claude Code in this project gives no orientation. The human operator must already know what the system does and how to interact with it. As new modules are added (remote sensing, vision, AI), this gap widens.

## Goal

When the human opens Claude Code in the `llm-gis` folder:
1. They are immediately greeted with what the workspace can do, in terms of needs — not commands.
2. Within a few seconds, they see the current system status: Docker health, incoming files, recent work.
3. The agent stays in operator mode — the human describes what they need, the agent handles the rest.

## Design

### Two-phase session start

**Phase 1 — Instant greeting (synchronous)**

As soon as the session opens, the agent prints a concise system card. High-level, need-oriented. No `bin/*` commands, no technical internals. Example:

```
llm-gis — Geospatial Analysis Workspace

What I can do for you:
  - Load vector or raster data into a spatial database
  - Run spatial analysis (buffers, intersections, aggregations, custom SQL)
  - Export results as GeoPackage or GeoJSON

Drop your files into data/incoming/ and tell me what you need.
```

**Phase 2 — Background status check (async background agent)**

Simultaneously, a background agent runs:
- `bin/doctor` — checks Docker and DB connectivity
- Scans `data/incoming/` for files
- `bin/list-ingestions --limit 5` — recent work

When it returns, a short status block is printed:

```
System: Docker running, DB healthy
Incoming: 2 files (roads.gpkg, elevation.tif)
Recent work: 1 ingestion from today (raw_20260330...)
```

If everything is healthy and incoming/recent are empty, it stays silent — no noise for no reason.

### Operator mode

CLAUDE.md instructs the agent to always translate human needs into workflows. The human never needs to think about `bin/` commands, ingest IDs, or CRS codes — the agent resolves those. The human's vocabulary is: "I have X, I need Y."

### Extensibility

When new modules are added:
1. Add one line to the greeting in `CLAUDE.md` under "What I can do"
2. Add the module's technical context to `hot-start` skill

No structural changes required. The greeting grows with the system.

## Files Changed

| File | Action |
|------|--------|
| `CLAUDE.md` (project root) | Create — intro behavior + operator mode instructions |
| `.claude/skills/hot-start/SKILL.md` | No change |

## Out of Scope

- Web frontend
- Persistent session state between conversations
- Any UI beyond the Claude Code CLI
