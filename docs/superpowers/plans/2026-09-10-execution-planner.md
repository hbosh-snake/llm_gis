# Execution Planner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `llm_gis/planner.py` and `bin/plan`, which explain — in one machine-readable object, executing nothing — which engine a job should use, why, and the exact `bin/*` steps that carry it out.

**Architecture:** One pure module, no I/O. `classify(uri)` derives format and locality from the URI's suffix and scheme; `route(...)` applies a small rule table whose only axis is whether the result must outlive the command; `steps(...)` renders the decision as copy-pasteable `bin/*` argv. `bin/plan` prints the object and exits. `catalog.py` imports the planner's `readers()` so format-to-engine knowledge lives in exactly one place.

**Tech Stack:** Python 3.12+, `uv`, Typer (CLI), stdlib dataclasses, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-10-execution-planner-design.md`

## Global Constraints

- Package manager is `uv`. `uv run pytest`, `uv add <pkg>`. Never `pip`, never `python3`.
- No new runtime dependencies in this phase.
- Existing command names, flags and JSON field names keep working. Additive changes only.
- `readable_by`'s returned values do not change. Verbatim from the spec: `readable_by = ["duckdb"] if format == "parquet" else []`.
- All tests in this plan run offline: no database, no network, no Docker. `uv run pytest` on the host must pass.
- No emojis in code. Short modules, short functions, docstrings over inline comments.
- Every command's stdout parses as JSON; errors go to stderr as a `GisError` envelope and exit 1.
- The planner opens nothing and executes nothing. If a step in this plan tempts you to read the source file, you have left the design.

## Vocabulary used throughout

Format constants: `"parquet"`, `"vector_file"`, `"postgis_table"`, `"raster"`.
Engine constants: `"duckdb"`, `"postgis"`.
Locality: `"local"`, `"remote"`.
Operations: `"query"`, `"analyse"`, `"export"`.

---

### Task 1: Classification and the readers table

**Files:**
- Create: `llm_gis/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `llm_gis.errors.GisError`, `llm_gis.errors.UNSUPPORTED_FORMAT`.
- Produces: `Source` dataclass with fields `uri: str`, `format: str`, `locality: str`, `readers: list[str]`; `classify(uri: str) -> Source`; `readers(format: str) -> list[str]`; the module constants `PARQUET`, `VECTOR_FILE`, `POSTGIS_TABLE`, `RASTER`, `DUCKDB`, `POSTGIS`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_planner.py`:

```python
"""The planner's rule table, asserted directly. Nothing here opens a file."""

from __future__ import annotations

import pytest

from llm_gis.errors import UNSUPPORTED_FORMAT, GisError
from llm_gis.planner import DUCKDB, POSTGIS, classify


def test_a_local_geoparquet_is_parquet_and_duckdb_only():
    source = classify("/data/incoming/buildings.parquet")
    assert source.format == "parquet"
    assert source.locality == "local"
    assert source.readers == [DUCKDB]


def test_a_remote_href_is_remote():
    assert classify("https://example.com/a/b.parquet").locality == "remote"
    assert classify("s3://bucket/b.parquet").locality == "remote"


def test_a_query_string_does_not_hide_the_suffix():
    """A signed URL carries its token after the path; duck.reader_sql splits the same way."""
    assert classify("https://example.com/b.parquet?token=abc").format == "parquet"


def test_a_geopackage_is_readable_by_both_engines():
    """DuckDB reads it with ST_Read; ingest-vector loads it. Both routes are real."""
    source = classify("/data/incoming/aoi.gpkg")
    assert source.format == "vector_file"
    assert source.readers == [DUCKDB, POSTGIS]


def test_a_schema_qualified_name_is_a_postgis_table():
    source = classify("analysis_aoi.result")
    assert source.format == "postgis_table"
    assert source.readers == [POSTGIS]


def test_a_raster_has_no_reader_yet():
    """Phase 7 owns cloud raster. Saying so beats guessing a route."""
    source = classify("/data/incoming/dem.tif")
    assert source.format == "raster"
    assert source.readers == []


def test_an_unrecognised_suffix_is_an_error_not_a_guess():
    with pytest.raises(GisError) as caught:
        classify("/data/incoming/notes.docx")
    assert caught.value.code == UNSUPPORTED_FORMAT
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_planner.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'llm_gis.planner'`.

- [ ] **Step 3: Write the minimal implementation**

Create `llm_gis/planner.py`:

```python
"""Which engine should run a job, and why.

Two engines serve this workspace and for some sources both of them work: a local
vector file can be read in place by DuckDB's ST_Read or ingested into PostGIS.
What separates them is whether the result has to outlive the command that made
it, and that is the only axis this module routes on. Size never branches a rule.

Nothing here opens a source. Format and locality come from the URI's suffix and
scheme, so the planner answers at discovery time, when the least is known.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from llm_gis.errors import UNSUPPORTED_FORMAT, GisError

PARQUET = "parquet"
VECTOR_FILE = "vector_file"
POSTGIS_TABLE = "postgis_table"
RASTER = "raster"

DUCKDB = "duckdb"
POSTGIS = "postgis"

LOCAL = "local"
REMOTE = "remote"

PARQUET_SUFFIXES = {".parquet", ".geoparquet", ".pq"}
VECTOR_SUFFIXES = {".gpkg", ".geojson", ".json", ".shp", ".fgb", ".kml", ".gml", ".gpx", ".csv"}
RASTER_SUFFIXES = {".tif", ".tiff", ".vrt"}
REMOTE_SCHEMES = ("http://", "https://", "s3://")

TABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")

READERS = {
    PARQUET: [DUCKDB],
    VECTOR_FILE: [DUCKDB, POSTGIS],
    POSTGIS_TABLE: [POSTGIS],
    RASTER: [],
}


@dataclass(frozen=True)
class Source:
    """What a URI is, as far as its text alone can say."""

    uri: str
    format: str
    locality: str
    readers: list[str]


def readers(format_: str) -> list[str]:
    """Engines that can open this format. What can, not what should.

    The one authoritative format-to-engine table in this workspace.
    `catalog.readable_by` is a projection of it.
    """
    return list(READERS[format_])


def _suffix(uri: str) -> str:
    """The suffix, with any query string removed, as duck.reader_sql does."""
    return Path(uri.split("?")[0]).suffix.lower()


def _format(uri: str) -> str:
    if "/" not in uri and TABLE_PATTERN.match(uri):
        return POSTGIS_TABLE
    suffix = _suffix(uri)
    if suffix in PARQUET_SUFFIXES:
        return PARQUET
    if suffix in RASTER_SUFFIXES:
        return RASTER
    if suffix in VECTOR_SUFFIXES:
        return VECTOR_FILE
    raise GisError(
        UNSUPPORTED_FORMAT,
        f"Nothing in this workspace recognises {uri}",
        "Give a Parquet, GeoParquet, vector file, raster, or a schema.table name",
        {"suffix": suffix or None},
    )


def classify(uri: str) -> Source:
    """Format, locality and candidate engines, from the URI's text alone."""
    format_ = _format(uri)
    locality = REMOTE if uri.startswith(REMOTE_SCHEMES) else LOCAL
    return Source(uri=uri, format=format_, locality=locality, readers=readers(format_))
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_planner.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add llm_gis/planner.py tests/test_planner.py
git commit -m "feat: classify a source into format, locality and candidate engines"
```

---

### Task 2: The rule table

**Files:**
- Modify: `llm_gis/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `Source`, `classify`, the format and engine constants from Task 1.
- Produces: `Route` dataclass with fields `strategy: str | None`, `reason: str`, `fallback: dict | None`, `overridden: str | None`, `warnings: list[dict]`, `blocked_by: dict | None`; `route(operation: str, source: Source, *, materialise: bool = False, engine: str | None = None) -> Route`; the constants `QUERY`, `ANALYSE`, `EXPORT`, `NO_CONVERSION_PATH`, `REMOTE_UNINDEXED_READ`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_planner.py`:

```python
from llm_gis.planner import NO_CONVERSION_PATH, route


def _route(operation, uri, **kwargs):
    return route(operation, classify(uri), **kwargs)


def test_a_remote_geoparquet_query_reads_in_place():
    result = _route("query", "https://example.com/buildings.parquet")
    assert result.strategy == DUCKDB
    assert result.fallback is None
    assert result.reason


def test_a_local_geopackage_query_prefers_duckdb_and_names_the_other_route():
    result = _route("query", "/data/incoming/aoi.gpkg")
    assert result.strategy == DUCKDB
    assert result.fallback["strategy"] == POSTGIS
    assert result.fallback["requires"]


def test_materialising_a_geopackage_query_goes_to_postgis():
    result = _route("query", "/data/incoming/aoi.gpkg", materialise=True)
    assert result.strategy == POSTGIS
    assert result.fallback["strategy"] == DUCKDB
    assert result.fallback["loses"] == "persistence"


def test_a_remote_vector_file_warns_about_the_read():
    result = _route("query", "https://example.com/aoi.gpkg")
    assert result.strategy == DUCKDB
    assert [w["code"] for w in result.warnings] == ["REMOTE_UNINDEXED_READ"]


def test_a_postgis_table_query_stays_in_postgis():
    assert _route("query", "analysis_aoi.result").strategy == POSTGIS


def test_analyse_always_uses_the_persistent_workspace():
    """Crossing sources in SQL is what the workspace is for; --materialise is moot."""
    assert _route("analyse", "/data/incoming/aoi.gpkg").strategy == POSTGIS
    assert _route("analyse", "/data/incoming/aoi.gpkg", materialise=False).strategy == POSTGIS


def test_exporting_a_file_never_enters_the_database():
    assert _route("export", "/data/incoming/buildings.parquet").strategy == DUCKDB
    assert _route("export", "analysis_aoi.result").strategy == POSTGIS


def test_materialising_a_parquet_source_is_blocked_with_the_reason():
    """GDAL here has no Parquet driver and duck-query writes Parquet. Say so."""
    result = _route("query", "/data/incoming/buildings.parquet", materialise=True)
    assert result.strategy is None
    assert result.blocked_by["code"] == NO_CONVERSION_PATH
    assert result.blocked_by["suggested_action"]


def test_analysing_a_parquet_source_is_blocked_the_same_way():
    result = _route("analyse", "https://example.com/buildings.parquet")
    assert result.strategy is None
    assert result.blocked_by["code"] == NO_CONVERSION_PATH


def test_a_raster_has_no_route_at_all():
    with pytest.raises(GisError) as caught:
        _route("query", "/data/incoming/dem.tif")
    assert caught.value.code == UNSUPPORTED_FORMAT


def test_an_engine_override_beats_the_rules_and_says_so():
    result = _route("query", "/data/incoming/aoi.gpkg", engine=POSTGIS)
    assert result.strategy == POSTGIS
    assert result.overridden == "engine"


def test_an_override_the_source_cannot_honour_is_refused():
    """An override is someone saying they know better; routing around them silently
    destroys the only signal that they were wrong."""
    with pytest.raises(GisError) as caught:
        _route("query", "analysis_aoi.result", engine=DUCKDB)
    assert caught.value.code == UNSUPPORTED_FORMAT
    assert caught.value.details["requested_engine"] == DUCKDB


def test_forcing_postgis_onto_parquet_reports_the_gap_rather_than_refusing():
    """An override cannot conjure a route that does not exist. Name the prerequisite."""
    result = _route("query", "https://example.com/b.parquet", engine=POSTGIS)
    assert result.strategy is None
    assert result.blocked_by["code"] == NO_CONVERSION_PATH
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_planner.py -v`
Expected: FAIL, `ImportError: cannot import name 'NO_CONVERSION_PATH'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `llm_gis/planner.py`:

```python
QUERY = "query"
ANALYSE = "analyse"
EXPORT = "export"
OPERATIONS = (QUERY, ANALYSE, EXPORT)

NO_CONVERSION_PATH = "NO_CONVERSION_PATH"
REMOTE_UNINDEXED_READ = "REMOTE_UNINDEXED_READ"

BLOCKED_PARQUET = {
    "code": NO_CONVERSION_PATH,
    "message": (
        "Nothing here writes a GDAL-readable file from a Parquet source: GDAL in this "
        "image has no Parquet driver, and duck-query --output writes Parquet."
    ),
    "suggested_action": (
        "Query in place without --materialise, or add a GPKG output format to duck-query "
        "(DuckDB supports COPY ... FORMAT GDAL)."
    ),
}


@dataclass
class Route:
    """One routing decision, with the argument for it."""

    strategy: str | None
    reason: str
    fallback: dict | None = None
    overridden: str | None = None
    warnings: list[dict] = field(default_factory=list)
    blocked_by: dict | None = None


def _blocked(reason: str) -> Route:
    return Route(strategy=None, reason=reason, blocked_by=dict(BLOCKED_PARQUET))


def _refuse_override(source: Source, engine: str) -> None:
    """An override the source cannot honour fails loudly rather than routing around it."""
    if engine not in source.readers:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"{engine} cannot open {source.uri}",
            f"Drop --engine, or use one of: {', '.join(source.readers) or 'no engine here'}",
            {"requested_engine": engine, "readers": source.readers},
        )


def _query_route(source: Source, materialise: bool) -> Route:
    if source.format == POSTGIS_TABLE:
        return Route(POSTGIS, "the table is already in the workspace")
    if source.format == PARQUET:
        if materialise:
            return _blocked("a Parquet source cannot reach the workspace today")
        return Route(DUCKDB, "DuckDB reads Parquet in place; no database is needed")
    if materialise:
        return Route(
            POSTGIS,
            "the result must survive this command, and the workspace is where results live",
            fallback={"strategy": DUCKDB, "requires": None, "loses": "persistence"},
        )
    warnings = []
    if source.locality == REMOTE:
        warnings.append(
            {
                "code": REMOTE_UNINDEXED_READ,
                "message": "A remote non-Parquet vector file is read whole and unindexed over HTTP",
                "severity": "warning",
            }
        )
    return Route(
        DUCKDB,
        "ST_Read opens a vector file without ingesting it, and no persistence was requested",
        fallback={"strategy": POSTGIS, "requires": "stage and ingest-vector first", "loses": None},
        warnings=warnings,
    )


def _analyse_route(source: Source) -> Route:
    if source.format == PARQUET:
        return _blocked("SQL across sources runs in the workspace, which Parquet cannot reach today")
    return Route(POSTGIS, "SQL across sources needs the persistent workspace")


def _export_route(source: Source) -> Route:
    if source.format == POSTGIS_TABLE:
        return Route(POSTGIS, "bin/export writes from the workspace")
    return Route(DUCKDB, "the source never enters the database")


def route(
    operation: str,
    source: Source,
    *,
    materialise: bool = False,
    engine: str | None = None,
) -> Route:
    """Which engine runs this operation on this source, and the argument for it."""
    if operation not in OPERATIONS:
        raise GisError(
            MISSING_ARGUMENT,
            f"Unknown operation: {operation}",
            f"Use one of: {', '.join(OPERATIONS)}",
        )
    if not source.readers:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"No engine here can open {source.uri}",
            "Cloud raster arrives in Phase 7; ingest-raster still loads a local raster",
            {"format": source.format},
        )

    if engine is not None:
        if engine == POSTGIS and source.format == PARQUET:
            return _blocked("a Parquet source cannot reach the workspace today")
        _refuse_override(source, engine)

    if operation == QUERY:
        decided = _query_route(source, materialise)
    elif operation == ANALYSE:
        decided = _analyse_route(source)
    else:
        decided = _export_route(source)

    if engine is not None and decided.strategy != engine:
        return Route(
            engine,
            f"requested with --engine {engine}, overriding: {decided.reason}",
            fallback={"strategy": decided.strategy, "requires": None, "loses": None},
            overridden="engine",
            warnings=decided.warnings,
        )
    if engine is not None:
        decided.overridden = "engine"
    return decided
```

Add `field` to the dataclasses import and `MISSING_ARGUMENT` to the errors import at the top of the file:

```python
from dataclasses import dataclass, field
from llm_gis.errors import MISSING_ARGUMENT, UNSUPPORTED_FORMAT, GisError
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_planner.py -v`
Expected: PASS, 20 tests.

- [ ] **Step 5: Commit**

```bash
git add llm_gis/planner.py tests/test_planner.py
git commit -m "feat: route an operation to an engine on the persistence axis"
```

---

### Task 3: The serial step list

**Files:**
- Modify: `llm_gis/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `Source`, `Route` from Tasks 1 and 2.
- Produces: `Step` dataclass with fields `command: str`, `argv: list[str]`, `why: str`; `steps(operation: str, source: Source, decided: Route, *, bbox: str | None = None, where: str | None = None, output: str | None = None, output_format: str = "gpkg", sql_path: str | None = None) -> list[Step]`.

Each `Step.argv` is what follows `bin/`. Every value the caller supplied appears verbatim, so a printed line pastes and runs.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_planner.py`:

```python
from llm_gis.planner import steps


def test_a_duckdb_query_is_one_step_carrying_the_real_arguments():
    source = classify("/data/incoming/aoi.gpkg")
    decided = route("query", source)
    plan = steps("query", source, decided, bbox="8.5,45.0,9.5,45.6", where="kind = 'wood'",
                 output="/data/outgoing/2026-09-10_aoi/matches.parquet")
    assert [s.command for s in plan] == ["duck-query"]
    assert plan[0].argv == [
        "/data/incoming/aoi.gpkg",
        "--bbox", "8.5,45.0,9.5,45.6",
        "--where", "kind = 'wood'",
        "--output", "/data/outgoing/2026-09-10_aoi/matches.parquet",
    ]


def test_omitted_arguments_leave_no_empty_flags():
    source = classify("https://example.com/b.parquet")
    plan = steps("query", source, route("query", source))
    assert plan[0].argv == ["https://example.com/b.parquet"]


def test_a_materialised_query_stages_ingests_and_exports():
    source = classify("/data/incoming/aoi.gpkg")
    decided = route("query", source, materialise=True)
    plan = steps("query", source, decided, bbox="8.5,45.0,9.5,45.6",
                 output="/data/outgoing/2026-09-10_aoi/result.gpkg")
    assert [s.command for s in plan] == ["stage", "ingest-vector", "export"]
    assert plan[0].argv == ["/data/incoming/aoi.gpkg", "--ingest-id", "aoi"]
    assert plan[1].argv == [
        "/data/work/staging/aoi/aoi.gpkg", "--table", "aoi", "--ingest-id", "aoi",
    ]
    assert plan[2].argv[0] == "/data/outgoing/2026-09-10_aoi/result.gpkg"
    assert "ST_MakeEnvelope(8.5,45.0,9.5,45.6, ST_SRID(geom))" in plan[2].argv[-1]


def test_the_ingest_id_is_derived_so_every_step_pastes_without_editing():
    """stage picks a timestamped id unless told one; the plan tells it one."""
    source = classify("/data/incoming/Milano AOI.gpkg")
    plan = steps("query", source, route("query", source, materialise=True))
    assert plan[0].argv[2] == "milano_aoi"


def test_an_analyse_plan_runs_sql_between_ingest_and_export():
    source = classify("/data/incoming/aoi.gpkg")
    decided = route("analyse", source)
    plan = steps("analyse", source, decided, sql_path="/data/work/sql/overlay.sql",
                 output="/data/outgoing/2026-09-10_aoi/result.gpkg")
    assert [s.command for s in plan] == ["stage", "ingest-vector", "run-sql", "export"]
    assert plan[2].argv == ["/data/work/sql/overlay.sql", "--ingest-id", "aoi"]


def test_a_blocked_route_produces_no_steps():
    source = classify("/data/incoming/buildings.parquet")
    decided = route("query", source, materialise=True)
    assert steps("query", source, decided) == []


def test_every_step_explains_itself():
    source = classify("/data/incoming/aoi.gpkg")
    plan = steps("query", source, route("query", source, materialise=True))
    assert all(s.why for s in plan)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_planner.py -v`
Expected: FAIL, `ImportError: cannot import name 'steps'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `llm_gis/planner.py`:

```python
@dataclass
class Step:
    """One bin/* invocation, with the reason it is in the list."""

    command: str
    argv: list[str]
    why: str


def _ingest_id(uri: str) -> str:
    """A deterministic id from the file name, so stage and ingest-vector agree.

    stage invents a timestamped id when it is not given one, which would make every
    later step in a printed plan unpasteable.
    """
    stem = Path(uri.split("?")[0]).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_")


def _flags(**pairs: str | None) -> list[str]:
    """Only the flags the caller actually supplied, in the order given."""
    argv = []
    for name, value in pairs.items():
        if value is not None:
            argv += [f"--{name.replace('_', '-')}", value]
    return argv


def _postgis_predicate(bbox: str | None, where: str | None) -> str:
    """The filter as SQL. ST_SRID(geom) keeps it correct without reading the file."""
    parts = []
    if bbox:
        parts.append(f"ST_Intersects(geom, ST_MakeEnvelope({bbox}, ST_SRID(geom)))")
    if where:
        parts.append(f"({where})")
    return f" WHERE {' AND '.join(parts)}" if parts else ""


def _materialise_steps(source: Source) -> list[Step]:
    ingest_id = _ingest_id(source.uri)
    name = Path(source.uri.split("?")[0]).name
    return [
        Step("stage", [source.uri, "--ingest-id", ingest_id],
             "copy the source into the workspace and hash it"),
        Step("ingest-vector",
             [f"/data/work/staging/{ingest_id}/{name}", "--table", ingest_id,
              "--ingest-id", ingest_id],
             "load it into PostGIS, where later steps can reach it"),
    ]


def steps(
    operation: str,
    source: Source,
    decided: Route,
    *,
    bbox: str | None = None,
    where: str | None = None,
    output: str | None = None,
    output_format: str = "gpkg",
    sql_path: str | None = None,
) -> list[Step]:
    """The serial bin/* list that carries out this route, arguments carried through."""
    if decided.strategy is None:
        return []

    if decided.strategy == DUCKDB:
        if operation == EXPORT:
            return [Step("duck-query", [source.uri, *_flags(output=output)],
                         "read the source and write the output file")]
        return [Step("duck-query",
                     [source.uri, *_flags(bbox=bbox, where=where, output=output)],
                     "filter the source in place")]

    if source.format == POSTGIS_TABLE:
        sql = f"SELECT * FROM {source.uri}{_postgis_predicate(bbox, where)}"
        return [Step("export",
                     [output or "/data/outgoing/result.gpkg", "--format", output_format,
                      "--sql", sql],
                     "write the filtered table out")]

    ingest_id = _ingest_id(source.uri)
    plan = _materialise_steps(source)
    if operation == ANALYSE:
        plan.append(
            Step("run-sql", [sql_path or "/data/work/sql/analysis.sql", "--ingest-id", ingest_id],
                 "run the analysis SQL against the ingested tables")
        )
        sql = f"SELECT * FROM analysis_{ingest_id}.result"
    else:
        sql = f"SELECT * FROM raw_{ingest_id}.{ingest_id}{_postgis_predicate(bbox, where)}"
    plan.append(
        Step("export",
             [output or "/data/outgoing/result.gpkg", "--format", output_format, "--sql", sql],
             "write the result out and QC it")
    )
    return plan
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_planner.py -v`
Expected: PASS, 27 tests.

- [ ] **Step 5: Commit**

```bash
git add llm_gis/planner.py tests/test_planner.py
git commit -m "feat: render a route as a copy-pasteable bin/* step list"
```

---

### Task 4: `bin/plan`

**Files:**
- Modify: `llm_gis/cli.py`
- Create: `bin/plan`
- Modify: `llm_gis/planner.py` (adds `plan()`)
- Test: `tests/test_plan_cli.py`

**Interfaces:**
- Consumes: `classify`, `route`, `steps` from Tasks 1-3.
- Produces: `planner.plan(operation, uri, *, materialise=False, engine=None, bbox=None, where=None, output=None, output_format="gpkg", sql_path=None, asset=None) -> dict` — the whole output object; and the `plan` Typer command.

- [ ] **Step 1: Write the failing test**

Create `tests/test_plan_cli.py`:

```python
"""bin/plan prints a plan and runs nothing."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from llm_gis.cli import app


def _run_ok(argv: list[str]) -> dict:
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_a_plan_carries_the_envelope_and_every_key():
    payload = _run_ok(["plan", "query", "/data/incoming/aoi.gpkg"])
    assert payload["status"] == "ok"
    assert payload["command"] == "plan"
    for key in ("operation", "source", "strategy", "reason", "fallback",
                "overridden", "warnings", "steps", "blocked_by"):
        assert key in payload


def test_the_remote_geoparquet_workflow_routes_to_duckdb():
    payload = _run_ok(["plan", "query", "https://example.com/b.parquet",
                       "--bbox", "8.5,45.0,9.5,45.6"])
    assert payload["strategy"] == "duckdb"
    assert payload["steps"][0]["command"] == "duck-query"
    assert "--bbox" in payload["steps"][0]["argv"]


def test_materialising_switches_the_route_and_the_steps():
    payload = _run_ok(["plan", "query", "/data/incoming/aoi.gpkg", "--materialise"])
    assert payload["strategy"] == "postgis"
    assert [s["command"] for s in payload["steps"]] == ["stage", "ingest-vector", "export"]


def test_a_blocked_plan_is_a_successful_answer_not_an_error():
    """'There is no route' answers the question that was asked."""
    payload = _run_ok(["plan", "query", "/data/incoming/b.parquet", "--materialise"])
    assert payload["strategy"] is None
    assert payload["steps"] == []
    assert payload["blocked_by"]["code"] == "NO_CONVERSION_PATH"


def test_an_impossible_override_exits_one_with_a_code():
    result = CliRunner().invoke(app, ["plan", "query", "analysis_aoi.result",
                                      "--engine", "duckdb"])
    assert result.exit_code == 1
    assert json.loads(result.stderr)["code"] == "UNSUPPORTED_FORMAT"


def test_the_planner_never_touches_the_source():
    """Every path above names a file that does not exist, and none of them failed."""
    payload = _run_ok(["plan", "query", "/nowhere/at/all/aoi.gpkg"])
    assert payload["strategy"] == "duckdb"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_plan_cli.py -v`
Expected: FAIL, exit code 2 — Typer has no `plan` command.

- [ ] **Step 3: Write the minimal implementation**

Append to `llm_gis/planner.py`:

```python
def plan(
    operation: str,
    uri: str,
    *,
    materialise: bool = False,
    engine: str | None = None,
    bbox: str | None = None,
    where: str | None = None,
    output: str | None = None,
    output_format: str = "gpkg",
    sql_path: str | None = None,
    asset: dict | None = None,
) -> dict:
    """The whole planning answer: the route, the argument for it, and the steps."""
    source = classify(uri)
    decided = route(operation, source, materialise=materialise, engine=engine)
    decided.warnings.extend(_asset_warnings(operation, asset))
    rendered = steps(
        operation, source, decided,
        bbox=bbox, where=where, output=output, output_format=output_format,
        sql_path=sql_path,
    )
    return {
        "operation": operation,
        "source": {
            "uri": source.uri,
            "format": source.format,
            "locality": source.locality,
            "readers": source.readers,
        },
        "strategy": decided.strategy,
        "reason": decided.reason,
        "fallback": decided.fallback,
        "overridden": decided.overridden,
        "warnings": decided.warnings,
        "blocked_by": decided.blocked_by,
        "steps": [{"command": s.command, "argv": s.argv, "why": s.why} for s in rendered],
    }


def _asset_warnings(operation: str, asset: dict | None) -> list[dict]:
    """Warnings a measured Asset supports and a URI cannot. Never a route change.

    Only measured top-level fields are read. A publisher's `advertised` claims are
    not measurements and Phase 4 quarantined them for that reason.
    """
    if not asset:
        return []
    warnings = []
    if operation == ANALYSE and asset.get("crs_status") == "suspicious":
        warnings.append(
            {
                "code": "CRS_SUSPICIOUS",
                "message": f"The described source reports a suspicious CRS: {asset.get('crs')}",
                "severity": "warning",
            }
        )
    if asset.get("record_count") == 0:
        warnings.append(
            {
                "code": "EMPTY_SOURCE",
                "message": "The described source measured zero records",
                "severity": "warning",
            }
        )
    return warnings
```

Add to `llm_gis/cli.py` — the import beside the others, then the command after `duck_query_cmd`:

```python
from llm_gis.planner import plan as plan_operation
```

```python
@app.command("plan")
@handle_errors
def plan_cmd(
    operation: str = typer.Argument(..., help="query, analyse or export"),
    uri: str = typer.Argument(..., help="Path, URL or schema.table of the source"),
    bbox: str | None = typer.Option(None, "--bbox", help="minx,miny,maxx,maxy in the source CRS"),
    where: str | None = typer.Option(None, "--where", help="SQL predicate on attributes"),
    output: str | None = typer.Option(None, "--output", help="Where the emitted steps should write"),
    output_format: str = typer.Option("gpkg", "--format", help="gpkg, geojson or parquet"),
    sql_path: str | None = typer.Option(None, "--sql-file", help="SQL file for an analyse plan"),
    engine: str | None = typer.Option(None, "--engine", help="Force duckdb or postgis"),
    materialise: bool = typer.Option(False, "--materialise/--no-materialise",
                                     help="The result must survive for later steps"),
    asset: Path | None = typer.Option(None, "--asset", help="An Asset JSON file for extra warnings"),
) -> None:
    """Explain which engine should run an operation, why, and the steps. Runs nothing."""
    asset_json = None
    if asset is not None:
        if not asset.exists():
            raise GisError(
                INPUT_NOT_FOUND,
                f"Asset file does not exist: {asset}",
                "Pass the JSON emitted by duck-describe, inspect or catalog-assets",
            )
        asset_json = json.loads(asset.read_text(encoding="utf-8"))
    _emit(
        "plan",
        plan_operation(
            operation, uri, materialise=materialise, engine=engine, bbox=bbox,
            where=where, output=output, output_format=output_format,
            sql_path=sql_path, asset=asset_json,
        ),
    )
```

Extend the errors import in `cli.py` to `from llm_gis.errors import INPUT_NOT_FOUND, UNEXPECTED, GisError`.

Create `bin/plan`, matching the existing wrapper idiom exactly:

```bash
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_env.sh"
docker compose --progress quiet run --rm agent uv run --quiet llm-gis plan "$@"
```

Then `chmod +x bin/plan`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_plan_cli.py -v && uv run pytest -q`
Expected: PASS, 6 new tests and the whole suite green.

- [ ] **Step 5: Commit**

```bash
git add llm_gis/planner.py llm_gis/cli.py bin/plan tests/test_plan_cli.py
git commit -m "feat: bin/plan explains a route and its steps without running them"
```

---

### Task 5: One table, two fields in `catalog.py`

**Files:**
- Modify: `llm_gis/catalog.py:42-47` (`readable_by`), `llm_gis/catalog.py:95` (`build_asset`), `llm_gis/catalog.py:108` (`_to_asset_json`)
- Modify: `llm_gis/asset.py` (adds the `readers` field)
- Test: `tests/test_stac_shape.py`

**Interfaces:**
- Consumes: `planner.classify`, `planner.readers`, the format constants.
- Produces: `Asset.readers: list[str]`; a `readers` key on every flattened asset. `readable_by` keeps its signature and its values.

Phase 4's design says `readable_by` "must not become a second, competing routing table". It is subsumed without changing what it returns: the planner holds the one table, and `readable_by` becomes a projection of it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_stac_shape.py`:

```python
def test_readable_by_still_returns_exactly_what_it_always_did():
    """A compatibility surface. Phase 6 subsumed the table underneath it, not the values."""
    assert readable_by("application/vnd.apache.parquet") == ["duckdb"]
    assert readable_by("application/x-parquet") == ["duckdb"]
    assert readable_by("image/tiff; application=geotiff; profile=cloud-optimized") == []
    assert readable_by(None) == []


def test_an_asset_also_reports_what_could_open_it_at_all():
    """readable_by answers 'can duck-query take this href'. readers answers 'what can open it'."""
    flat = flatten_asset(
        "data",
        {"href": "https://example.com/aoi.gpkg", "type": "application/geopackage+sqlite3"},
        {},
    )
    assert flat["readable_by"] == []
    assert flat["readers"] == ["duckdb", "postgis"]


def test_a_parquet_asset_agrees_with_itself():
    flat = flatten_asset(
        "data",
        {"href": "https://example.com/b.parquet", "type": "application/vnd.apache.parquet"},
        {},
    )
    assert flat["readable_by"] == ["duckdb"]
    assert flat["readers"] == ["duckdb"]


def test_an_href_the_planner_does_not_recognise_reports_no_readers():
    """catalog-assets lists whatever a publisher advertises; it must not raise on a stray href."""
    flat = flatten_asset("thumb", {"href": "https://example.com/x.png", "type": "image/png"}, {})
    assert flat["readers"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_stac_shape.py -v`
Expected: FAIL, `KeyError: 'readers'`.

- [ ] **Step 3: Write the minimal implementation**

In `llm_gis/asset.py`, beside `readable_by`:

```python
    readable_by: list[str] = field(default_factory=list)
    readers: list[str] = field(default_factory=list)
```

In `llm_gis/catalog.py`, replace `readable_by` and add its sibling:

```python
from llm_gis.planner import DUCKDB, classify


def readable_by(media_type: str | None) -> list[str]:
    """Whether duck-query can consume this href directly. A compatibility surface.

    Phase 6 subsumed the routing table this once held: `planner.readers` is now the
    single authoritative one, and this is a projection of it. The returned values are
    unchanged, and deliberately narrower than `readers`: a GeoPackage over HTTP can be
    opened by DuckDB, but not by the Parquet query path this field describes.
    """
    return [DUCKDB] if media_type in PARQUET_MEDIA_TYPES else []


def readers_for(href: str | None) -> list[str]:
    """What could open this href at all, per the planner. Never raises on a stray asset."""
    if not href:
        return []
    try:
        return classify(href).readers
    except GisError:
        return []
```

`GisError` must also be imported from `llm_gis.errors` in `catalog.py` if it is not already. Note the import direction: `catalog` imports `planner`, never the reverse — the planner depends on nothing but `errors`.

In `build_asset`, beside the existing line:

```python
        readable_by=readable_by(asset.get("type")),
        readers=readers_for(asset.get("href")),
```

In `_to_asset_json`, beside the existing key:

```python
        "readable_by": asset.readable_by,
        "readers": asset.readers,
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_stac_shape.py tests/test_catalog_operations.py tests/test_asset.py -v && uv run pytest -q`
Expected: PASS, including every pre-existing `readable_by` assertion unchanged.

- [ ] **Step 5: Commit**

```bash
git add llm_gis/catalog.py llm_gis/asset.py tests/test_stac_shape.py
git commit -m "feat: catalog assets report planner readers beside readable_by"
```

---

### Task 6: Documentation

**Files:**
- Modify: `docs/llm/OUTPUT_SCHEMA.md` (new `bin/plan` section after `bin/duck-query`; the `bin/catalog-assets` section)
- Modify: `docs/llm/QUICKSTART.md`
- Modify: `.claude/skills/hot-start/SKILL.md`

Per `CLAUDE.md`: a new module's technical context goes in the hot-start skill.

- [ ] **Step 1: Add the `bin/plan` section to `docs/llm/OUTPUT_SCHEMA.md`**

Insert after the `bin/duck-query` table:

```markdown
### `bin/plan`

Explains a route. Executes nothing: no file is opened, no database is contacted, and a
source that does not exist plans exactly like one that does.

| Key | Type | Meaning |
|---|---|---|
| `operation` | string | `"query"`, `"analyse"` or `"export"`, as given. |
| `source` | object | `{uri, format, locality, readers}` — what the URI's text alone says. |
| `strategy` | string or null | `"duckdb"`, `"postgis"`, or null when no route exists. |
| `reason` | string | Why that engine, in one sentence. Always about persistence or capability, never performance. |
| `fallback` | object or null | `{strategy, requires, loses}` — the other viable engine, what it costs, what it gives up. |
| `overridden` | string or null | `"engine"` when `--engine` beat the rules, else null. |
| `warnings` | array | `{code, message, severity}`, as `bin/qc` uses. |
| `blocked_by` | object or null | `{code, message, suggested_action}` when `strategy` is null. |
| `steps` | array | `{command, argv, why}` per step. `argv` is what follows `bin/`, ready to paste. |

A blocked plan exits 0. "There is no route" is an answer to the question asked, not a failure.
```

- [ ] **Step 2: Extend the `bin/catalog-assets` section in the same file**

Add the `readers` row, and this note under the table:

```markdown
`readable_by` and `readers` differ on purpose. `readable_by` answers "can `duck-query`
consume this href directly", which for a GeoPackage is no. `readers` answers "what could
open this at all", which for the same GeoPackage is `["duckdb", "postgis"]` — DuckDB via
`ST_Read`, PostGIS via `ingest-vector`. `readers` comes from `planner.readers`, the one
place format-to-engine knowledge lives; `readable_by` is a narrower projection of it, kept
as a compatibility surface.
```

- [ ] **Step 3: Add one line to `docs/llm/QUICKSTART.md`**

Under the workflow section, in the document's existing voice:

```markdown
When a job could go either way — a local vector file can be filtered in place or ingested —
run `bin/plan query <source>` first. It prints the route, the reason, and the steps, and runs
nothing.
```

- [ ] **Step 4: Add the planner to `.claude/skills/hot-start/SKILL.md`**

In the module list, matching the surrounding entries' voice:

```markdown
- `llm_gis/planner.py` — which engine runs a job and why. Pure: classifies a URI by suffix
  and scheme, applies a small rule table whose only axis is whether the result must outlive
  the command, and renders the decision as a `bin/*` step list. `bin/plan` prints it and
  executes nothing. `planner.readers` is the single authoritative format-to-engine table;
  `catalog.readable_by` is a projection of it.
```

- [ ] **Step 5: Verify and commit**

Run: `uv run pytest -q`
Expected: PASS, unchanged from Task 5.

```bash
git add docs/llm/OUTPUT_SCHEMA.md docs/llm/QUICKSTART.md .claude/skills/hot-start/SKILL.md
git commit -m "docs: bin/plan output schema and the readers/readable_by distinction"
```

---

### Task 7: Field test

**Files:**
- Create: `docs/reports/2026-09-10_phase6_field_test.md`

The plan's standing rule: a phase is not done until a real job has been run end to end through the `bin/*` commands. Here the specific risk is a plan whose steps do not paste and run, which no unit test catches.

- [ ] **Step 1: Bring the stack up and run the five done-when cases**

```bash
docker compose up -d
bin/plan query https://<a real public GeoParquet href> --bbox 8.5,45.0,9.5,45.6
bin/plan query /data/incoming/<a real gpkg>
bin/plan query /data/incoming/<a real gpkg> --materialise --output /data/outgoing/2026-09-10_phase6/result.gpkg
bin/plan query /data/incoming/<a real parquet> --materialise
bin/catalog-assets <a real STAC item url> | tee /tmp/assets.json
```

Record each object. Case 4 must return `strategy: null` with `NO_CONVERSION_PATH` and exit 0.

- [ ] **Step 2: Run the emitted steps verbatim**

Take the `argv` from case 3's plan and run each as `bin/<command> <argv...>`, in order, changing nothing. This is the test: the ingest id, the staged path and the export SQL must all line up without editing.

- [ ] **Step 3: Confirm the Phase 4 route reaches the same answer from an href**

Feed a GeoParquet href from the `catalog-assets` output to `bin/plan query <href>` and confirm `strategy: duckdb` and a `duck-query` step naming that href. Check the same asset's `readers` and `readable_by` values in the `catalog-assets` output.

- [ ] **Step 4: Write the report**

`docs/reports/2026-09-10_phase6_field_test.md`, following the existing reports' shape: what was run, what each plan said, whether every emitted step pasted and ran unedited, and what the run surfaced that the suite could not. Record failures as findings for the next phase rather than fixing them here, unless a step simply does not run — a plan that prints an unrunnable step is a Phase 6 bug and must be fixed before the phase is done.

- [ ] **Step 5: Commit**

```bash
git add docs/reports/2026-09-10_phase6_field_test.md
git commit -m "docs: Phase 6 field test report"
```

---

## Self-review notes

Spec coverage checked section by section: module (Tasks 1-3), output shape (Task 4), blocked case (Tasks 2 and 4), overrides (Task 2), one table two fields (Task 5), `--asset` (Task 4), errors (Tasks 1, 2, 4), testing (all tasks), documentation (Task 6), done when (Task 7).

Two things the spec left implicit and this plan decides, both flagged for review at the task that makes them:

- **The ingest id is derived from the file stem** (Task 3). `stage` invents a timestamped id when not given one, which would make every later step of a printed plan unpasteable. A deterministic id is what makes "copy-pasteable" true rather than aspirational.
- **A materialised query uses `export --sql`, not `run-sql`** (Task 3). `run-sql` needs a SQL file the planner does not have; `export --sql` already exists and takes the filter directly. `run-sql` appears only in an `analyse` plan, where the caller supplies the file.
