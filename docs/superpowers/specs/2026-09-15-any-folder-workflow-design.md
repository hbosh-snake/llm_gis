# Any-folder workflow — first working version design

Status: Revised to incorporate the user's 2026-09-15 review. This supersedes the earlier translated-path design. Any-folder implementation has not started. Preview fix 50e7c01 was tested, fast-forwarded into local main, and included by rebasing the feature branch.

Implementation plan: [five-task plan](../plans/2026-09-15-any-folder-workflow.md).

## Outcome

Open Codex or Claude in any supported local folder, ask a geodata question, and receive actual analytical values in chat or artifacts in the requested folder. Default unspecified artifact destinations to `./results/`. Preserve sources and report metric units, QC warnings and truncated results.

Scope is the existing Linux host with local Docker Compose and one shared database. Reserved container roots and the user's whole home directory cannot be caller/mount roots; use a project subfolder. Files directly in HOME and tokens resolving to HOME or / produce a clear "move it into a subfolder" error before Docker. Remote Docker, Windows and an MCP service are outside this first version.

## Architecture

One small uv-run host launcher mounts caller/input/output folders at the same absolute paths in the container and sets container cwd to the caller's folder. It selects the backend with explicit Compose file/project directory and `uv run --project /workspace`, preserving caller cwd even when that folder has its own unrelated Python project.

Inputs are mounted read-only. Existing external argument paths contribute additional read-only mounts without changing argument strings or reinterpreting SQL/table values. Only known output operands need command-specific parsing. Create their parent directories on the host and mount them writable. Refuse conflicting mount roots and any existing output; do not write plan --output. A writable output folder cannot replace the caller/source read-only mount. A separate child folder is the usual destination.

Each invocation removes its own tmp directory on exit while retaining staging/reports/logs. Full job cleanup is deferred, so staged copies currently accumulate. Each invocation gets a unique host work directory under the repo's data/work/jobs, bound at the same absolute path and supplied as LLM_GIS_WORK_ROOT. This isolates raster/window and other intermediates and makes returned staging/log paths usable by later calls. The launcher resolves output operands to absolute paths before invoking the backend. For preview it injects an explicit results/ output stem when absent; the legacy backend default remains data/work/preview/. Collision checks use the backend's exact with_suffix naming, including dotted stems. No result translation or planner-step rewriting is needed.

Sources retain their original locations. Stage accepts incoming_root plus optional os.pathsep-separated LLM_GIS_SOURCE_ROOTS, rejecting `/`. Generated ingest IDs append six random hex characters to avoid the current same-file/same-second collision while staying under Postgres identifier limits. Explicitly reused IDs are unchanged and not concurrency-protected in this version.

## Query answers

Add query-sql separately from unchanged run-sql. It accepts one inline SQL query or SQL file, optional ingest context and timeout, with SELECT/VALUES through a read-only transaction and named cursor. SHOW and EXPLAIN are unsupported. A live test must prove multi-statement rejection and acceptance of literal semicolons; do not assume ordinary psycopg execute always rejects batches or split SQL text.

Return typed columns, positional rows, returned count, truncation, omissions and warnings. Preview defaults are 100 rows and 262144 bytes of serialized row payload; maxima are 10000 and 4194304. Fetch an extra row to detect truncation, and never slice values. Column/envelope metadata is not part of this simple row-byte budget.

Geometry/geography are recognized using database type OIDs and omitted with binary columns. Decimal becomes an exact string, datetime an ISO value, UUID a string, and non-finite floats null with a warning. Optional complete CSV/JSON export continues beyond the preview cap and reports exported count. Failure removes only the partial file created by that invocation and never reports it complete. Spatial artifacts continue through existing export.

## Skills and delivery

One versioned global skill template serves both Codex and Claude. Both explicitly load shared operating instructions and invoke the launcher with the original session cwd. Respect explicit requests for other tools and ask about genuine source/layer/CRS ambiguity. Default analytic answers are grounded in returned rows; artifacts use the user's selected folder.

A simple uv-run installer creates the launcher symlink and both skills. The existing personal skill diffs must be shown and the user's explicit OK received before either installed skill is replaced. No installer hash/backup infrastructure. Align both hot-start skills, AGENTS.md/CLAUDE.md and CLI/output docs, including current tests, schema creation and ingest-ID format.

## Five delivery tasks

1. Same-path launcher, job workspaces, output refusal, structured errors and host test isolation.
2. Stage source roots and random ingest suffix. Launcher task 1 owns default preview output injection and absolute output arguments; backend path behavior stays unchanged.
3. Read-only query-sql, bounded rows and complete CSV/JSON export.
4. Shared global skill, simple installer and documentation alignment.
5. First-version acceptance, concurrency and one fresh real session per agent.

## First-version acceptance

1. From an external folder with spaces, obtain known polygon count and metric area in chat.
2. Obtain the ten largest polygons, ordered deterministically with correct values.
3. Clip and export to an explicit relative destination; independently re-read contents, CRS, QC and ownership, and confirm unchanged sources.
4. Concurrent jobs using generated IDs and distinct destinations do not collide in files or schemas; include raster workspace isolation.
5. One fresh Codex and one fresh Claude session select the skill without naming it, return evidence-based answers and link the artifact. Report unavailable client testing as unverified, separately from CLI checks.

Tests calling host Docker live under tests/host, run via uv run pytest tests/host with explicit live marker selection when needed, and are excluded from bin/test. Fake Docker tests verify launcher arguments without Docker. Run existing backend regression tests and doctor.

## Deferred until after the first real job

Overwrite; new DuckDB/raster row previews; installer content hashes/backups; locks for explicit ingest IDs; concurrent same-destination publication races; hardlink/symlink identity handling; escaping symlink-sidecar detection; contract_version; full job folder cleanup beyond per-call tmp removal. No staging/publication/translation subsystem is planned. The earlier broad ten-case acceptance suite is narrowed to the first-version cases above.
