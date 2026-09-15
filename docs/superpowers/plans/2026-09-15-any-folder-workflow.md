# Any-folder Workflow: First Working Version Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task. Execute inline unless the user requests delegation. This plan incorporates the user's review of 2026-09-15 and supersedes the earlier eight-task plan.

**Goal:** Open Codex or Claude in an unrelated local folder, obtain actual geodata answers in chat, and save requested artifacts into the selected folder.

**Architecture:** One small host launcher mounts folders at their original absolute paths and preserves the caller's cwd. Existing Docker GIS commands do the analysis; a new read-only query-sql command returns bounded rows or complete JSON/CSV. One global skill template supplies both agents.

**Tech Stack:** Linux, local Docker Compose, uv, existing Python/Typer/psycopg/PostGIS/GDAL dependencies, pytest. Host Python runs through `uv run --script`.

**Spec:** `docs/superpowers/specs/2026-09-15-any-folder-workflow-design.md`.

## Preflight and branch

Already performed during review revision:

- Preserved AGENTS.md and CLAUDE.md edits in the stash named `Preserve operator instructions before any-folder planning` on fix/preview-output-aux-xml. Keep that stash intact; do not pop it over subsequent documentation changes.
- Created `feat/any-folder-workflow` from main, then fast-forwarded local main to preview fix `50e7c01` and rebased the feature branch onto it after the second review.
- Preview fix `50e7c01` is now on local main and the feature branch. `bin/test tests/test_preview.py` passed all 8 tests before the merge. No remote push was performed.

Before implementation, verify `git status --short`, `git branch --show-current`, and `git stash list`. Inspect the preserved instruction diff when updating docs; bring forward relevant operator guidance deliberately, without deleting the stash or restoring stale instructions wholesale.

## First-version boundaries

Implement launcher, extra staging roots, randomized ingest IDs, preview default, query-sql, both global skills, documentation and acceptance cases 1–3 plus concurrency and real-client checks.

Defer until after the first real job: overwrite support; DuckDB/raster row previews; installer content hashes/backups; locks for explicit ingest IDs; concurrent output-publication races; hardlink/symlink identity checks; escaping symlink-sidecar detection; contract_version; job folder cleanup beyond per-call tmp removal. No path translation, synthetic mount names, staging/publishing subsystem, broad input operand registry, new MCP server, or arbitrary DuckDB SQL.

Legacy bin wrappers keep container paths and run-sql semantics. The global launcher accepts host paths. Explicitly reused ingest IDs and simultaneous jobs writing the identical destination are outside the first-version concurrency guarantee. Separate jobs with generated IDs and distinct destinations must work.

## Technical corrections retained after review

1. The launcher resolves known output operands against the caller cwd and passes absolute paths to the backend. For preview without --output, it inserts an explicit absolute results/ stem. Leave backend output/default behavior unchanged, use a host-addressable absolute work root, and do not rewrite results or planner steps.
2. With `-w <caller cwd>`, plain `uv run llm-gis` could discover the user's unrelated project or no project. Use `uv run --project /workspace --quiet llm-gis ...` inside the container. `--project` selects the backend without changing cwd, unlike `--directory`. See [uv CLI reference](https://docs.astral.sh/uv/reference/cli/).
3. Verified the installed psycopg `_server_cursor_base.py`: `_declare_gen` calls `_execute_send(pgq, force_extended=True)`. Named cursors reject multiple statements through the extended protocol. Keep the live test for batch rejection and literal semicolons; no fallback or SQL splitting is needed.
4. An output mount identical to the caller/source mount would replace its read-only protection. Refuse that conflict; a selected child output directory such as results/ is supported. Exact known source/output filename equality is refused. Broad identity/race defenses remain deferred.

## Task 1: Small same-path launcher and host test separation

**Files:** Create `bin/llm-gis`, `tests/host/test_launcher.py`. Modify `bin/test`, `docs/llm/OUTPUT_SCHEMA.md`.

Keep launcher helpers in the one script, using only the standard library. Use an executable uv script shebang (`#!/usr/bin/env -S uv run --script`) and inline script metadata with no dependencies so it does not sync the caller's project. Resolve the actual repo through the launcher symlink, not cwd. Host tests may load the script with runpy to exercise pure helpers.

**Interfaces:**

```python
def normalize_outputs(args: list[str], cwd: Path) -> list[str]: ...
# Only known output operands become absolute; insert preview --output if absent.
def output_paths(args: list[str], cwd: Path) -> list[Path]: ...
def mounts_for(args: list[str], cwd: Path, outputs: list[Path],
               work_dir: Path) -> list[tuple[Path, bool]]: ...  # path, writable

def docker_argv(repo: Path, cwd: Path, args: list[str],
                mounts: list[tuple[Path, bool]], work_dir: Path) -> list[str]: ...
def main(args: list[str] | None = None) -> int: ...
```

- [ ] Add fake-Docker host tests first. Fake executable records argv/env/cwd to a temp JSON file and emits `{"status":"ok","command":"doctor"}`. Put the fake first on PATH; invoke the actual launcher from `tmp_path/'client folder with spaces'`.

```python
def test_launcher_keeps_caller_cwd_and_selects_backend(fake_docker, repo, tmp_path):
    cwd = tmp_path / 'client folder with spaces'; cwd.mkdir()
    result = subprocess.run([str(repo/'bin/llm-gis'), 'doctor'], cwd=cwd,
                            env=fake_docker.env, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    argv = json.loads(fake_docker.record.read_text())['argv']
    assert argv[argv.index('--workdir') + 1] == str(cwd)
    assert argv[argv.index('--project-directory') + 1] == str(repo)
    assert argv[-7:] == ['uv', 'run', '--project', '/workspace', '--quiet', 'llm-gis', 'doctor']
```

Fixture `fake_docker` exposes the injected environment and record path, and `repo = Path(__file__).resolve().parents[2]`.

- [ ] Run `uv run pytest tests/host/test_launcher.py -q`; observe the missing launcher failure before writing it.
- [ ] Build Docker argv using arrays, never shell evaluation:

```text
docker compose --progress quiet -f <repo>/docker-compose.yml
  --project-directory <repo> run --rm
  --volume <cwd>:<cwd>:ro
  [--volume <external-parent>:<external-parent>:ro ...]
  [--volume <output-parent>:<output-parent>:rw ...]
  --volume <job-dir>:<job-dir>:rw
  --workdir <cwd>
  -e LLM_GIS_WORK_ROOT=<job-dir>
  -e TMPDIR=<job-dir>/tmp
  -e LLM_GIS_SOURCE_ROOTS=<os.pathsep-joined-source-roots>
  agent uv run --project /workspace --quiet llm-gis <args with absolute output operands>
```

Set LLM_GIS_UID/GID in the host subprocess environment before Compose interpolation, using os.getuid/getgid. Passing only container `-e` values would not set Compose's `user:` field.

- [ ] Allocate `<repo>/data/work/jobs/<uuid>` on the host, create tmp/log/report/staging children, and bind the job directory at the *same host path*. Set WORK_ROOT to this path, so reports and staged files are reusable on a later invocation with no `/data` translation. Keep the existing Compose mounts intact.
- [ ] Mount cwd read-only. For argument tokens (also values after `=`) that are existing external files/directories, add their parent/source directory read-only, deduplicating mounts. Keep argument strings unchanged, including SQL text, URLs and schema.table. Extra mounts do not change argument semantics. Catch path-probe OSError for long SQL strings. Do not discover arbitrary files by parsing SQL text.
- [ ] Only parse output operands: export's positional output, and --output for preview/raster-window/duck-query. Handle `--output=value`, options before the export positional, and option arities for export; no full input registry. Add query-sql when Task 3 wires it. `plan --output` is never created or mounted writable. Resolve each written output operand against cwd and replace only that operand with its absolute path. For preview with no --output, append --output and the absolute `(cwd / "results" / Path(dataset).stem)` stem. Keep all input operands and SQL text unchanged. The backend preview default remains work_root()/preview/.
- [ ] Output parents are resolved against cwd and created by the host user. Refuse existing files before Docker; preview computes exactly `stem.with_suffix(".png")` and `stem.with_suffix(".preview.json")` and checks both. A default stem from parcels.v2.gpkg therefore produces parcels.png and parcels.preview.json, matching the unchanged backend. Add dotted-basename and explicit dotted-stem collision tests; auxiliary-file handling is unnecessary after 50e7c01. No --overwrite option in this version.
- [ ] Refuse dynamically requested mount targets at or under `/data`, `/workspace`, `/opt`, `/usr`, `/etc`, `/var`, `/proc`, `/sys`, `/dev`, `/root`, plus `/` and the user's home itself. Apply checks to actual resolved mount roots, including symlinks and output parents. Reject exact RO/RW mount conflicts and writable ancestors of source mounts. Permit a writable child of cwd only when no known source lies within that child. Document this first-version restriction with an actionable new-subfolder suggestion.
- [ ] Return existing structured backend errors unchanged; wrap Docker/non-JSON/permission/mount errors as `{status:'error',code,message,suggested_action,details}` on stderr with nonzero exit. Success stdout must remain a JSON object. Put raw Docker stderr in the job log. No automatic rebuild/startup workflow beyond existing Compose run behavior.
- [ ] Give root errors an actionable message: for a file directly in HOME, or a token such as .. resolving to HOME or /, say "move it into a subfolder" and identify the refused mount root. Validate before Docker, not as a generic mount failure.
- [ ] Remove only this invocation's `<job>/tmp` in a finally block on success or failure. Preserve staging/reports/logs for later calls and diagnostics. Cleanup failure must be reported as a warning without hiding the primary error. Full job/staging retention cleanup is a documented deferred gap.
- [ ] Expand tests: absolute external source, path spaces/quotes, unchanged SQL/URL/table tokens, unused plan output, output exists, all reserved roots, HOME files and .. diagnostics, nested output folder, no source-write mount, dotted preview collision names, explicit injected preview output, tmp removal on success/failure, retained staging/logs, and different job roots on repeated invocations.
- [ ] Exclude host tests in `bin/test` via `--ignore=tests/host`; host tests run with `uv run pytest tests/host`. Document bin/llm-gis in OUTPUT_SCHEMA. Run focused host tests and `bin/test tests/test_output_contract.py`; commit Task 1.

## Task 2: Extra source roots and ingest-ID suffix

**Files:** Modify only `llm_gis/common.py` and `llm_gis/stage.py`. Extend `tests/test_work_root.py`; add `tests/test_ingest_ids.py`. Backend preview defaults and exporter/query/raster output semantics stay unchanged.

**Interfaces:** `allowed_source_roots() -> tuple[Path, ...]`, `ensure_source_path(path: Path) -> None`; existing `make_ingest_id(source_hash: str) -> str` remains callable unchanged.

- [ ] Write tests for legacy incoming root, two os.pathsep-separated extra roots, a rejected outside path, rejected `/` root, and resolved containment. Keep the default no-env behavior unchanged.
- [ ] Freeze the timestamp in the ingest-ID test, call twice with one hash, and assert different IDs; each matches `14 digits_10 hash chars_6 hex chars`, and `len('analysis_'+id) <= 63`.

```python
def test_ingest_ids_fit_postgres_identifiers():
    ids = [make_ingest_id('a' * 64) for _ in range(2)]
    assert ids[0] != ids[1]
    assert all(re.fullmatch(r'\d{14}_a{10}_[0-9a-f]{6}', x) for x in ids)
    assert all(len('analysis_' + x) <= 63 for x in ids)
```

- [ ] Run `bin/test tests/test_work_root.py tests/test_ingest_ids.py` and confirm new failures.
- [ ] Parse optional LLM_GIS_SOURCE_ROOTS using os.pathsep, include incoming_root(), resolve roots, reject `/`, and replace stage's single-root containment check with ensure_source_path. Do not change unrelated command source rules.
- [ ] Append `secrets.token_hex(3)` to generated ingest IDs in common.py. Preserve explicitly supplied IDs. Update documentation/tests that assert the old format. Do not introduce locks or claim collision-proof explicit reuse.
- [ ] Leave raster work naming unchanged: unique WORK_ROOT per launcher call isolates raster/window. Confirm two fake invocations get unique absolute job directories, and a staged host path can be used as next invocation's input.
- [ ] Run focused tests plus existing ingest/output contract tests; commit Task 2.

## Task 3: Read-only query-sql with bounded chat rows and full export

**Files:** Create `llm_gis/query_sql.py`, `bin/query-sql`, `tests/test_query_sql.py`; modify `llm_gis/cli.py`, `llm_gis/errors.py`, `bin/llm-gis`, `docs/llm/OUTPUT_SCHEMA.md`. Keep serialization helpers inside query_sql.py for this first version.

**Interface:**

```python
def query_sql(*, statement: str | None = None, sql_file: Path | None = None,
              ingest_id: str | None = None, statement_timeout: str = '5min',
              max_rows: int = 100, max_bytes: int = 262144,
              output: Path | None = None, output_format: str = 'json') -> dict: ...
```

CLI: exactly one of `--sql` and `--sql-file`; optional `--ingest-id`, `--statement-timeout`, `--max-rows`, `--max-bytes`, `--output`, `--format json|csv`. Default rows=100, row-payload budget=262144 bytes; allowed maxima 10000 rows and 4194304 bytes. Budget measures the sum of UTF-8 serialized row bytes, excluding columns/envelope; document that distinction. Do not slice values.

Result fields: engine=postgis, columns (name/type/encoding), positional rows, returned_row_count, truncated, truncation_reason, omitted_columns, warnings, optional output_path/output_format/exported_row_count. Duplicate names are retained through positional rows. Omit total count when unknown.

- [ ] Add failing unit tests for exactly one SQL source, limit validation, Decimal/datetime/UUID/non-finite encoding, duplicate column names, empty result, huge first row, exact boundaries and complete export independent of preview.

```python
@pytest.mark.live
def test_named_cursor_rejects_batch_but_accepts_literal_semicolon():
    assert query_sql(statement="SELECT ';' AS value")['rows'] == [[';']]
    with pytest.raises(GisError):
        query_sql(statement='SELECT 1; SELECT 2')

@pytest.mark.live
def test_full_export_outlives_preview_limit(tmp_path):
    out = tmp_path / 'all.json'
    r = query_sql(statement='SELECT generate_series(1,3) AS n',
                  max_rows=1, output=out)
    assert r['rows'] == [[1]]
    assert r['truncated'] is True
    assert r['exported_row_count'] == 3
    assert len(json.loads(out.read_text())['rows']) == 3
```

- [ ] Run `bin/test tests/test_query_sql.py`; confirm failure before implementation.
- [ ] Set conn.read_only=True before a transaction. Inside it, bind `set_config('statement_timeout', %s, true)`, set optional search_path using psycopg identifiers, and query geometry/geography OIDs from pg_type. Do not create schemas and do not modify run-sql.
- [ ] Use a named server-side cursor for SELECT/VALUES (including supported WITH SELECT). Document SHOW and EXPLAIN as unsupported rather than adding alternate execution paths. Named cursors already force the extended protocol; retain the batch regression test and never split semicolons or validate using startswith SELECT.
- [ ] Geometry/geography OIDs and bytea are omitted from result columns/rows and listed in omitted_columns; hex geometry strings cannot be detected by their Python type. Decimal -> exact string, datetime/date/time -> ISO 8601, UUID -> string, NaN/Inf -> null with warning. Preserve null. JSON/array values need recursive non-finite handling. Warn when omitting unsupported values rather than emitting Python repr.
- [ ] Fetch max_rows+1 for preview-only queries; stop adding preview rows when row count or cumulative encoded row bytes exceeds the limit. One extra row proves truncation. A first oversized row returns no preview rows with byte-limit truncation. Fetch full-export queries in bounded batches, continue writing after preview fills, and report actual exported count. Do not let the preview cap change the SQL query or the full export.
- [ ] Write CSV/JSON directly to an exclusive-created output (refuse existing) and close it on all paths. On query failure remove only the partial file created by this invocation; never report success for it. CSV uses empty fields for null, documented as lossy, while JSON preserves null/types through column metadata. Complete artifacts omit the same unsupported geometry/binary columns; request spatial export through the existing export command.
- [ ] Add live cases: write/DDL/data-modifying CTE rejection with unchanged fixture data, timeout via pg_sleep, semicolon literal and batch, empty results, byte truncation with Unicode, geometry OID omission, deterministic ORDER BY, and full CSV/JSON counts. Tests use unique fixture schemas and clean up only their fixtures.
- [ ] Add bin/query-sql, Typer command, query-sql --output launcher handling, and OUTPUT_SCHEMA documentation in this same task (no registration before command implementation). Run focused unit tests and `bin/test -m live tests/test_query_sql.py`; commit Task 3.

## Task 4: One skill template, simple installer and aligned docs

**Files:** Create `skills/llm-gis/SKILL.md.in`, `scripts/install-global.py`, `docs/llm/GLOBAL_WORKFLOW.md`, `tests/host/test_install_global.py`. Modify README.md, AGENTS.md, CLAUDE.md as needed, both `.codex/skills/hot-start/SKILL.md` and `.claude/skills/hot-start/SKILL.md`, docs/llm/QUICKSTART.md, README.md, manifest.json and OUTPUT_SCHEMA.md.

**Interface:** `uv run --script scripts/install-global.py [--check] [--replace]`. Default installs both agents and ~/.local/bin/llm-gis symlink. Codex path honors CODEX_HOME when set; otherwise ~/.codex/skills/llm-gis/SKILL.md. Claude path is ~/.claude/skills/llm-gis/SKILL.md. No dependency on the caller's project environment.

- [ ] Write host tests with temporary home paths for new install, identical rerun, --check unified diff, existing custom skill, and conflicting launcher. Installer tests pass a test-specific home path into the install function; production code does not rewrite HOME. Differing existing files require --replace. No content-hash database or backup system.
- [ ] Run `uv run pytest tests/host/test_install_global.py -q`; confirm failures.
- [ ] Render both skills from the same template with absolute launcher/repo paths. Explicitly load GLOBAL_WORKFLOW.md and AGENTS.md; do not rely on cd refreshing instructions. Invoke launcher with caller cwd and host paths, using absolute launcher path when PATH lacks ~/.local/bin. Do not edit shell profiles automatically.
- [ ] Guide automatic selection for geodata tasks, explicit alternative-tool requests, inspection/layer/CRS decisions, actual chat values via query-sql, and full artifacts in desired folder (default ./results/). Explain that DuckDB/raster new row previews are deferred; existing raster statistics remain usable. A partial rowset is labeled partial, not the whole answer. Avoid exposing backend mechanics unless useful/requested.
- [ ] Reconcile stale schema-creation, ingest-ID format and test-directory claims. Preserve operator-mode guidance from the saved stash through deliberate edits, with user-facing analytical choices retained. Distinguish legacy /data paths from same-path global usage and the blocked root/output-mount cases.
- [ ] Run installer --check against both existing personal skills and show the actual unified diff to the user. STOP and wait for the user's explicit OK before overwriting either ~/.claude/skills/llm-gis/SKILL.md or ~/.codex/skills/llm-gis/SKILL.md. This approval gate is explicitly required by the second review. Continue independent tests/docs while awaiting approval; elapsed time is not approval. After requested changes, show the revised diff and obtain approval for that replacement.
- [ ] Validate rendered skills using `uv run --with pyyaml <skill-creator>/scripts/quick_validate.py <rendered-skill-folder>`, and run host installer tests plus output-contract tests. Commit repository templates/docs and install the reviewed versions, keeping home files outside Git.

## Task 5: First-version acceptance and handoff

**Files:** Create `tests/host/test_any_folder_live.py`, `docs/reports/2026-09-15-any-folder-workflow.md`. All tests invoking host Docker live under tests/host and are excluded by bin/test. Mark real Docker host cases live; run explicitly with `uv run pytest tests/host -m live`. Unit fake-Docker cases run with `uv run pytest tests/host` using existing default marker exclusion.

- [ ] Create external fixture folder with spaces and a second input folder. Use generated/copied small polygon fixtures whose counts and metric areas are known independently. No tests operate on the user's actual source files.

```python
def host_call(repo, cwd, *args):
    r = subprocess.run([str(repo/'bin/llm-gis'), *args], cwd=cwd,
                       text=True, capture_output=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)
```

- [ ] Spec case 1: ingest from external folder and query actual count/area; compare to fixture values and metric units, with no requested user artifact.
- [ ] Spec case 2: query ten largest polygons with `ORDER BY area DESC, fid`, verify order and values. Small result must fit in chat without parsing a psql log.
- [ ] Spec case 3: clip and export into an explicit relative child destination. Re-read artifact using GDAL/GeoPandas and verify contents, CRS, QC warnings, absolute output path and ownership. Hash source files before/after to verify no mutation.
- [ ] Run two jobs on the same source simultaneously with generated IDs and distinct destinations. Assert different schemas/job directories and correct outputs; include raster-window workspace isolation. Host test of caller directory with unrelated pyproject verifies uv --project /workspace still runs this backend while keeping caller cwd.
- [ ] Negative coverage: existing output refused before fake Docker runs; invalid root/mount conflicts; malformed SQL/multiple statements; timeout; missing Docker; inaccessible destination. Confirm parseable errors and no false success. Identical-destination races remain deferred.
- [ ] Run `bin/doctor`, `bin/test`, `uv run pytest tests/host`, `uv run pytest tests/host -m live`, and `bin/test -m live tests/test_query_sql.py`. Record actual outcomes and failures, not assumed readiness.
- [ ] Open one fresh Claude and one fresh Codex session in an external fixture folder. Ask without skill names: “How many polygons are in parcels.gpkg and what is their total area in square metres?”, “Show the ten largest parcels”, and “Clip parcels.gpkg to boundary.gpkg and save results/clipped.gpkg”. Verify skill selection, query evidence and final artifact link. Do not use unrelated existing conversations. If either client cannot be exercised, report it as unverified separately from CLI results.
- [ ] Review final diff, record deferred items and first-job feedback in report, and commit tests/report. Deliver launcher path, skill paths, test evidence, and any unverified client checks. The first release is ready only when cases 1–3 and distinct-destination concurrency pass; do not claim both-agent seamlessness without actual client evidence.

## Self-review coverage

User review sections 1–2: same-path launcher, five first-version tasks and explicit deferrals above.
Code notes 1–4: stage roots, per-job work, six-hex ingest suffix and output preflight in Tasks 1–2.
Code note 5: read-only named-cursor query, limits, encodings and live protocol tests in Task 3, with the general execute claim corrected.
Code notes 6–10: OUTPUT_SCHEMA, tests/host exclusion, real installed-skill diff, uv-only Python invocation and sequential command wiring in Tasks 1, 3–5.
The only application change incorporated during plan review is the already-tested preview fix 50e7c01 merged into main. Any-folder implementation begins when the user requests execution.

## Second-review verification

- Preview fix merged into local main and feature branch rebased; 8 preview tests passed.
- Launcher owns preview default injection and absolute output operands; backend wrappers retain prior behavior.
- Installed-skill replacement waits for explicit user approval after the diff.
- Named-cursor force_extended=True verified locally; no fallback remains.
- Per-call tmp cleanup, deferred full job retention, exact dotted-stem collision checks and actionable HOME/root errors are specified.
