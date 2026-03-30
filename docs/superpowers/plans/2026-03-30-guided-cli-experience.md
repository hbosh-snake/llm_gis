# Guided CLI Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the human opens Claude Code in this project, they immediately see a focused system card and shortly after a background status report, with the agent staying in operator mode throughout.

**Architecture:** A single `CLAUDE.md` at the project root drives all behavior — it instructs the agent to greet instantly with a high-level system card, dispatch a background agent for health/context checks, and always translate human needs into workflows without exposing `bin/*` commands.

**Tech Stack:** Claude Code CLAUDE.md instructions, Claude Code background Agent tool.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `CLAUDE.md` | Create | Session-start behavior: greeting, background check, operator mode |
| `.claude/skills/hot-start/SKILL.md` | No change | Technical reference for the agent |

---

### Task 1: Create CLAUDE.md with greeting and operator mode

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Create CLAUDE.md**

Create `/home/ema/Projects/llm-gis/CLAUDE.md` with this exact content:

```markdown
# llm-gis

## Session start

When a new conversation begins in this project, do two things immediately:

**1. Print this greeting (verbatim, no additions):**

```
llm-gis — Geospatial Analysis Workspace

What I can do for you:
  - Load vector or raster data into a spatial database
  - Run spatial analysis (buffers, intersections, aggregations, custom SQL)
  - Export results as GeoPackage or GeoJSON

Drop your files into data/incoming/ and tell me what you need.
```

**2. Dispatch a background agent** with this prompt:

> Run these three commands in sequence and return a short status report:
> 1. `bin/doctor` — check if Docker and DB are healthy
> 2. `ls data/incoming/` — list files waiting to be ingested
> 3. `bin/list-ingestions --limit 5` — show recent work
>
> Return a plain-text status block in this format:
> ```
> System: <healthy / ERROR: <message>>
> Incoming: <N files (<name1>, <name2>, ...) / none>
> Recent work: <summary of most recent ingestion, or "none">
> ```
> If everything is healthy and both incoming and recent are empty, return nothing.

When the background agent completes, print its output as-is (if non-empty).

---

## Operator mode

You are the operator of this geospatial workspace. The human describes what they need in plain terms. You handle all the mechanics: inspecting files, resolving CRS, choosing the right commands, writing SQL, chaining the workflow end to end.

**The human's vocabulary is: "I have X, I need Y."**

Never ask the human to run `bin/*` commands directly. Never expose ingest IDs, CRS codes, or schema names unless they ask. Resolve these yourself using the available commands.

When in doubt about CRS or data quality, run `bin/inspect` first and report what you find in plain terms before proceeding.

---

## Adding new capabilities

When new modules are added to this workspace (remote sensing, vision, AI, etc.):
1. Add one line under "What I can do for you" in the greeting above.
2. Add the module's technical context to `.claude/skills/hot-start/SKILL.md`.

No other changes needed.
```

- [ ] **Step 2: Verify the file looks right**

Read back `CLAUDE.md` and confirm:
- Greeting section is present and verbatim
- Background agent dispatch prompt is complete
- Operator mode section is present
- Extensibility note is present

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "feat: add CLAUDE.md with guided session start and operator mode"
```

---

### Task 2: Smoke test

**Files:**
- No changes

- [ ] **Step 1: Verify CLAUDE.md is in place**

```bash
ls -la CLAUDE.md
```
Expected: file exists, non-zero size.

- [ ] **Step 2: Open a new Claude Code session in this folder**

Start a fresh Claude Code conversation. Confirm:
- The system card prints immediately without you asking anything
- A background agent fires and returns a status block within a few seconds
- The agent does not expose `bin/*` commands in the greeting

This is a manual verification step. No automated test is needed — the behavior is driven by instructions to the LLM, not by code logic.
