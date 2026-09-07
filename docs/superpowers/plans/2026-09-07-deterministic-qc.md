# Deterministic QC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `bin/qc` command and an automatic QC block on `export` that report deterministic metrics for a vector/raster file or a PostGIS table, plus five named warnings raised only when the caller supplied the context to judge them.

**Architecture:** Backend-specific collectors normalise every source into one metrics dict; a list of pure check functions turns that dict plus a declared context into `{status, checks, warnings}`. Collectors do all the I/O, checks do none, so every warning code is testable from a literal dict.

**Tech Stack:** Python 3.12, `uv`, Typer, psycopg 3, DuckDB (spatial), GDAL CLI (`ogrinfo`, `gdalinfo`), pyproj, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-deterministic-qc-design.md`

## Global Constraints

- Package manager is `uv`. `uv add <pkg>`, `uv run <cmd>`. Never `pip`, never `python3`.
- `data/incoming/` is read-only. Produced files go to `data/outgoing/`. Never write a sidecar next to a source file.
- Existing command names, flags and JSON field names keep working. Additive changes only.
- No emojis in code. Short modules, short functions, docstrings over inline comments. No defensive programming.
- All dynamic SQL uses `psycopg.sql.Identifier`, never f-string interpolation of identifiers.
- Column names are lowercase; the geometry column is `geom` and the primary key is `fid` for ingested tables.
- Non-live tests must pass on the host with no database. They may rely on a warm DuckDB extension cache, exactly as `tests/test_duck.py` already does.
- `tests/test_output_contract.py::test_output_schema_lists_every_bin_command` fails the suite if a new `bin/*` command is missing from `docs/llm/OUTPUT_SCHEMA.md`. Any task adding a `bin/` entry must update that document in the same commit.

## Deviations from the spec, decided here

Three, all structural rather than behavioural. Flag them at review; nothing else departs from the approved design.

1. **Two modules, not one.** The spec says `llm_gis/qc.py` holds collectors and checks. This plan splits them: `llm_gis/qc_collect.py` (all I/O) and `llm_gis/qc.py` (context, checks, envelope, dispatch). They change for different reasons and the split is what makes Task 1 testable with no backend at all.
2. **`geometry_types` stays DuckDB's per-feature histogram**, with OGR's declared type recorded alongside as `declared_geometry_type`. The spec gives OGR authority on disagreement; a declared layer type is a single string, not a histogram, so the two are kept as separate facts rather than one overwriting the other. OGR keeps sole authority over `has_z` and `has_m`, as the spec requires.
3. **The PostGIS vector collector runs three queries, not two** (schema, aggregate, geometry-type histogram). The spec's "two queries, not one" was correcting an assumption of one; the histogram needs its own `GROUP BY`.

---

## File Structure

| File | Responsibility |
|---|---|
| `llm_gis/qc.py` (create) | `QcContext`, the five check functions, `CHECKS`, `build_report`, `resolve_source`, `qc_report`. No I/O beyond calling collectors. |
| `llm_gis/qc_collect.py` (create) | The four collectors. All GDAL, DuckDB and psycopg calls live here. |
| `llm_gis/cli.py` (modify) | `qc` subcommand; `--no-qc` and `--compare-to` on `export`. |
| `llm_gis/exporter.py` (modify) | Attach the QC block to the export result. |
| `llm_gis/duck.py` (modify) | `reader_sql(uri)` helper, shared by `query`-style reads and QC. |
| `bin/qc` (create) | Three-line wrapper matching the existing idiom. |
| `tests/test_qc_checks.py` (create) | All five codes from literal dicts. No I/O. |
| `tests/test_qc_file.py` (create) | Real file collectors against fixtures. |
| `tests/live/test_qc_postgis.py` (create) | Table collector and export integration, `live` marked. |
| `tests/fixtures/make_fixtures.py` (modify) | Adds `dirty.gpkg` and `aoi_3d.gpkg`. |
| `docs/llm/OUTPUT_SCHEMA.md`, `README.md`, `AGENTS.md`, `.claude/skills/hot-start/SKILL.md` (modify) | Command, warning codes, and the warning-vs-error distinction. |

---

### Task 1: Context, checks and envelope

Pure logic only. No database, no GDAL, no DuckDB. This task alone satisfies the plan's "warning codes covered by fixture tests".

**Files:**
- Create: `llm_gis/qc.py`
- Modify: `pyproject.toml`
- Test: `tests/test_qc_checks.py`

**Interfaces:**
- Consumes: `llm_gis.common.crs_status`, `llm_gis.common.parse_crs`, `llm_gis.common.utc_now`; `llm_gis.errors.CRS_MISSING`, `CRS_SUSPICIOUS`.
- Produces: `QcContext(expect_non_empty: bool, metric_op: bool, id_column: str | None, reference: dict | None)`; `build_report(source: dict, metrics: dict, context: QcContext) -> dict`; `reproject_bbox(bbox: dict, src_crs: str | None, dst_crs: str | None) -> dict | None`; `CHECKS: list[Callable[[dict, QcContext], dict]]`.

- [ ] **Step 1: Declare pyproj explicitly**

`common.py` already imports `pyproj` and gets it transitively through `geopandas`. QC uses `pyproj.Transformer` directly, so it becomes a direct dependency.

```bash
uv add "pyproj>=3.6"
```

Expected: `pyproject.toml` gains `pyproj>=3.6` under `dependencies`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_qc_checks.py`:

```python
"""Every warning code, driven from literal metrics dicts. No I/O of any kind."""

from __future__ import annotations

import pytest

from llm_gis.qc import QcContext, build_report, reproject_bbox

BBOX = {"minx": 10.0, "miny": 45.0, "maxx": 10.3, "maxy": 45.3}


def _metrics(**overrides) -> dict:
    base = {
        "crs": "EPSG:4326",
        "bbox": dict(BBOX),
        "vector": {
            "feature_count": 4,
            "geometry_types": {"POLYGON": 4},
            "declared_geometry_type": "Polygon",
            "empty_count": 0,
            "invalid_count": 0,
            "has_z": False,
            "has_m": False,
            "area_stats": {"min": 0.01, "max": 0.01, "mean": 0.01, "sum": 0.04},
            "length_stats": None,
            "null_counts": {"name": 0},
            "duplicate_id_count": 0,
            "id_column": "fid",
        },
        "raster": None,
    }
    base.update(overrides)
    return base


def _source(kind: str = "file") -> dict:
    return {"kind": kind, "ref": "/tmp/x.gpkg", "dataset_kind": "vector"}


def _check(report: dict, code: str) -> dict:
    return next(c for c in report["checks"] if c["code"] == code)


def test_a_clean_dataset_with_no_context_is_ok():
    report = build_report(_source(), _metrics(), QcContext())
    assert report["status"] == "ok"
    assert report["warnings"] == []


def test_unsupplied_context_is_not_evaluated_never_pass():
    """The distinction the whole envelope exists for."""
    report = build_report(_source(), _metrics(feature_count=0), QcContext())
    for code in [
        "EMPTY_RESULT_UNEXPECTED",
        "RESULT_BBOX_DISJOINT_FROM_INPUT",
        "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION",
    ]:
        assert _check(report, code)["result"] == "not_evaluated"


def test_crs_missing_warns_without_any_context():
    report = build_report(_source(), _metrics(crs=None), QcContext())
    assert _check(report, "CRS_MISSING")["result"] == "warn"
    assert report["status"] == "warning"
    assert [w["code"] for w in report["warnings"]] == ["CRS_MISSING"]


def test_crs_suspicious_warns_and_carries_the_reason():
    metrics = _metrics(crs="EPSG:3035", bbox=dict(BBOX))
    report = build_report(_source(), metrics, QcContext())
    check = _check(report, "CRS_SUSPICIOUS")
    assert check["result"] == "warn"
    assert "lon/lat" in check["message"]


def test_geographic_crs_warns_only_when_the_operation_is_metric():
    metrics = _metrics()
    assert _check(build_report(_source(), metrics, QcContext()), "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION")["result"] == "not_evaluated"
    warned = build_report(_source(), metrics, QcContext(metric_op=True))
    assert _check(warned, "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION")["result"] == "warn"


def test_projected_crs_passes_a_metric_operation():
    metrics = _metrics(crs="EPSG:3035", bbox={"minx": 4e6, "miny": 2e6, "maxx": 4.1e6, "maxy": 2.1e6})
    report = build_report(_source(), metrics, QcContext(metric_op=True))
    assert _check(report, "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION")["result"] == "pass"


def test_empty_result_warns_only_when_declared_unexpected():
    metrics = _metrics()
    metrics["vector"]["feature_count"] = 0
    report = build_report(_source(), metrics, QcContext(expect_non_empty=True))
    assert _check(report, "EMPTY_RESULT_UNEXPECTED")["result"] == "warn"


def test_a_non_empty_result_passes_the_empty_check():
    report = build_report(_source(), _metrics(), QcContext(expect_non_empty=True))
    assert _check(report, "EMPTY_RESULT_UNEXPECTED")["result"] == "pass"


def test_disjoint_bboxes_warn():
    reference = {"ref": "raw_x.parcels", "crs": "EPSG:4326",
                 "bbox": {"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0}}
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "warn"


def test_overlapping_bboxes_pass():
    reference = {"ref": "raw_x.parcels", "crs": "EPSG:4326", "bbox": dict(BBOX)}
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "pass"


def test_a_null_bbox_cannot_be_compared():
    reference = {"ref": "raw_x.parcels", "crs": "EPSG:4326", "bbox": None}
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "not_evaluated"


def test_bbox_comparison_crosses_crs():
    """The same ground area in EPSG:3035 must not read as disjoint."""
    reference = {
        "ref": "raw_x.parcels",
        "crs": "EPSG:3035",
        "bbox": reproject_bbox(dict(BBOX), "EPSG:4326", "EPSG:3035"),
    }
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "pass"


def test_reproject_bbox_is_a_noop_for_the_same_crs():
    assert reproject_bbox(dict(BBOX), "EPSG:4326", "EPSG:4326") == BBOX


def test_raster_metrics_skip_the_vector_only_checks():
    metrics = {"crs": "EPSG:4326", "bbox": dict(BBOX), "vector": None,
               "raster": {"width": 20, "height": 20, "band_count": 1,
                          "resolution": {"x": 0.01, "y": 0.01}, "bands": [],
                          "stats_mode": "approximate"}}
    source = {"kind": "file", "ref": "/tmp/x.tif", "dataset_kind": "raster"}
    report = build_report(source, metrics, QcContext(expect_non_empty=True))
    assert _check(report, "EMPTY_RESULT_UNEXPECTED")["result"] == "not_evaluated"


def test_every_check_appears_exactly_once():
    report = build_report(_source(), _metrics(), QcContext())
    codes = [c["code"] for c in report["checks"]]
    assert len(codes) == len(set(codes)) == 5


def test_warnings_are_the_warn_subset_in_the_plans_shape():
    report = build_report(_source(), _metrics(crs=None), QcContext())
    warning = report["warnings"][0]
    assert set(warning) == {"code", "message", "severity"}
    assert warning["severity"] == "warning"
```

- [ ] **Step 3: Run it and watch it fail**

Run: `uv run pytest tests/test_qc_checks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm_gis.qc'`.

- [ ] **Step 4: Write `llm_gis/qc.py`**

Only the parts this task needs. `resolve_source` and `qc_report` arrive in Tasks 2 and 4.

```python
"""Deterministic quality control over a dataset or a table.

Metrics are collected by llm_gis.qc_collect; everything here is pure. A check
reports pass, warn, or not_evaluated, and never guesses at context it was not
given: an unsupplied comparison is not a passing one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pyproj import Transformer

from llm_gis.common import crs_status, parse_crs, utc_now
from llm_gis.errors import CRS_MISSING, CRS_SUSPICIOUS

SEVERITY = "warning"


@dataclass(frozen=True)
class QcContext:
    """What the caller declared about the job that produced this data."""

    expect_non_empty: bool = False
    metric_op: bool = False
    id_column: str | None = None
    reference: dict[str, Any] | None = None


def _result(code: str, result: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": SEVERITY, "result": result, "message": message}


def reproject_bbox(bbox: dict[str, float] | None, src_crs: str | None, dst_crs: str | None) -> dict[str, float] | None:
    """Transform a bbox, densifying the edges so a curved edge is not clipped off."""
    if bbox is None or not src_crs or not dst_crs or src_crs == dst_crs:
        return bbox
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    minx, miny, maxx, maxy = transformer.transform_bounds(
        bbox["minx"], bbox["miny"], bbox["maxx"], bbox["maxy"]
    )
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["maxx"] < b["minx"] or b["maxx"] < a["minx"] or a["maxy"] < b["miny"] or b["maxy"] < a["miny"]
    )


def check_crs_missing(metrics: dict, context: QcContext) -> dict:
    status, _ = crs_status(metrics.get("crs"), metrics.get("bbox"))
    if status == "missing":
        return _result(CRS_MISSING, "warn", "No CRS detected on this dataset")
    return _result(CRS_MISSING, "pass", f"CRS present: {metrics.get('crs')}")


def check_crs_suspicious(metrics: dict, context: QcContext) -> dict:
    status, reasons = crs_status(metrics.get("crs"), metrics.get("bbox"))
    if status == "suspicious":
        return _result(CRS_SUSPICIOUS, "warn", "; ".join(reasons))
    if status == "missing":
        return _result(CRS_SUSPICIOUS, "not_evaluated", "No CRS to judge")
    return _result(CRS_SUSPICIOUS, "pass", "CRS is plausible for the extent")


def check_geographic_crs_for_metric_operation(metrics: dict, context: QcContext) -> dict:
    code = "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION"
    if not context.metric_op:
        return _result(code, "not_evaluated", "No metric operation declared; pass --metric-op to check")
    crs = parse_crs(metrics.get("crs"))
    if crs is None:
        return _result(code, "not_evaluated", "CRS absent or unparseable")
    if crs.is_geographic:
        return _result(code, "warn", f"{metrics.get('crs')} is geographic; areas and distances will be in degrees")
    return _result(code, "pass", f"{metrics.get('crs')} is projected")


def check_empty_result_unexpected(metrics: dict, context: QcContext) -> dict:
    code = "EMPTY_RESULT_UNEXPECTED"
    vector = metrics.get("vector")
    if vector is None:
        return _result(code, "not_evaluated", "Not a vector dataset")
    if not context.expect_non_empty:
        return _result(code, "not_evaluated", "Emptiness not declared unexpected; pass --expect-non-empty to check")
    if vector["feature_count"] == 0:
        return _result(code, "warn", "Result has no features, but features were expected")
    return _result(code, "pass", f"{vector['feature_count']} features present")


def check_result_bbox_disjoint_from_input(metrics: dict, context: QcContext) -> dict:
    code = "RESULT_BBOX_DISJOINT_FROM_INPUT"
    reference = context.reference
    if reference is None:
        return _result(code, "not_evaluated", "No reference given; pass --compare-to to check")
    subject_bbox = metrics.get("bbox")
    if subject_bbox is None or reference.get("bbox") is None:
        return _result(code, "not_evaluated", "One of the two extents is empty")
    reference_bbox = reproject_bbox(reference["bbox"], reference.get("crs"), metrics.get("crs"))
    if reference_bbox is None:
        return _result(code, "not_evaluated", "Reference extent could not be reprojected")
    if _intersects(subject_bbox, reference_bbox):
        return _result(code, "pass", f"Extent overlaps {reference['ref']}")
    return _result(code, "warn", f"Extent does not overlap {reference['ref']} at all")


CHECKS: list[Callable[[dict, QcContext], dict]] = [
    check_crs_missing,
    check_crs_suspicious,
    check_geographic_crs_for_metric_operation,
    check_empty_result_unexpected,
    check_result_bbox_disjoint_from_input,
]


def build_report(source: dict, metrics: dict, context: QcContext) -> dict[str, Any]:
    """Run every check and assemble the envelope."""
    checks = [check(metrics, context) for check in CHECKS]
    warnings = [
        {"code": c["code"], "message": c["message"], "severity": c["severity"]}
        for c in checks
        if c["result"] == "warn"
    ]
    return {
        "qc_status": "warning" if warnings else "ok",
        "source": source,
        "metrics": metrics,
        "checks": checks,
        "warnings": warnings,
        "created_at": utc_now(),
    }
```

Note the key is `qc_status`, not `status`. `cli._emit` overwrites a top-level `status` with `"ok"`, and the QC block is nested inside export results where a bare `status` would read ambiguously. The CLI presents it under both names for `bin/qc` in Task 5.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_qc_checks.py -v`
Expected: PASS, 16 tests.

The `qc_status` rename means the test file's two `report["status"]` assertions must become `report["qc_status"]`. Fix them in `tests/test_qc_checks.py`, do not change `qc.py`.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: PASS, nothing regressed.

- [ ] **Step 7: Commit**

```bash
git add llm_gis/qc.py tests/test_qc_checks.py pyproject.toml uv.lock
git commit -m "feat: QC context, checks and report envelope"
```

---

### Task 2: File collectors

**Files:**
- Create: `llm_gis/qc_collect.py`
- Modify: `llm_gis/duck.py`, `llm_gis/qc.py`, `tests/fixtures/make_fixtures.py`
- Test: `tests/test_qc_file.py`

**Interfaces:**
- Consumes: `QcContext`, `build_report` (Task 1); `llm_gis.duck.connect`, `duck._geo_metadata`, `duck._crs_from_geo_metadata`; `llm_gis.common.run_command`, `normalize_crs`, `crs_text_from_ogr_coordinate_system`.
- Produces: `duck.reader_sql(uri: str) -> str`; `qc_collect.file_metrics(path: Path) -> tuple[dict, dict]` returning `(source, metrics)`; `qc.resolve_source(ref: str) -> dict`; `qc.qc_report(ref: str, context: QcContext) -> dict`.

- [ ] **Step 1: Verify three DuckDB behaviours before relying on them**

The spec requires this and it is cheap. Run each and record the answer in the commit message.

```bash
uv run python - <<'PY'
from pathlib import Path
from llm_gis.duck import connect
gpkg = str(Path("tests/fixtures/aoi.gpkg"))
c = connect()
print("A parameterised ST_Read:", c.execute("SELECT count(*) FROM ST_Read(?)", [gpkg]).fetchone())
print("B columns:", c.execute("DESCRIBE SELECT * FROM ST_Read(?)", [gpkg]).fetchall())
try:
    print("C ST_HasZ:", c.execute("SELECT bool_or(ST_HasZ(geom)) FROM ST_Read(?)", [gpkg]).fetchone())
except Exception as e:
    print("C ST_HasZ unsupported:", e)
PY
```

Decisions this settles:
- **A fails** → build the reader with a quoted, single-quote-escaped literal path instead of `?`, in `reader_sql`. Inputs are local paths from the CLI, not user SQL.
- **B** names the geometry column; use whatever the GEOMETRY-typed column is called rather than assuming `geom`.
- **C fails** → `has_z`/`has_m` come from `ogrinfo` only, and are `None` for a Parquet source. This is the expected outcome and the spec already gives OGR authority.

- [ ] **Step 2: Add the fixtures**

Append to `tests/fixtures/make_fixtures.py` and call both from `__main__`:

```python
def make_dirty_gpkg() -> None:
    """One self-intersecting polygon and one null attribute, so invalid_count
    and null_counts see real data rather than zeros."""
    from shapely.geometry import Polygon

    bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    gdf = gpd.GeoDataFrame(
        {"id": [1, 2], "name": ["ok", None]},
        geometry=[box(10.0, 45.0, 10.1, 45.1), bowtie],
        crs="EPSG:4326",
    )
    gdf.to_file(FIXTURES_DIR / "dirty.gpkg", driver="GPKG")


def make_aoi_3d_gpkg() -> None:
    """Z coordinates, so has_z is exercised against a real 3D layer."""
    from shapely.geometry import Polygon

    ring = [(10.0, 45.0, 100.0), (10.1, 45.0, 100.0), (10.1, 45.1, 100.0), (10.0, 45.0, 100.0)]
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[Polygon(ring)], crs="EPSG:4326")
    gdf.to_file(FIXTURES_DIR / "aoi_3d.gpkg", driver="GPKG")
```

Run: `uv run python tests/fixtures/make_fixtures.py`
Expected: `tests/fixtures/dirty.gpkg` and `tests/fixtures/aoi_3d.gpkg` exist, each a few KB. Confirm the bowtie is genuinely invalid:

```bash
uv run python -c "import geopandas as g; d=g.read_file('tests/fixtures/dirty.gpkg'); print(d.is_valid.tolist(), d['name'].isna().sum())"
```
Expected: `[True, False] 1`.

- [ ] **Step 3: Write the failing test**

Create `tests/test_qc_file.py`:

```python
"""File collectors against the committed fixtures. Offline, given a warm
DuckDB extension cache -- the same caveat tests/test_duck.py carries."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_gis.errors import INPUT_NOT_FOUND, GisError
from llm_gis.qc import QcContext, qc_report

FIXTURES = Path(__file__).parent / "fixtures"


def test_a_clean_geopackage_reports_its_metrics():
    report = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext())
    metrics = report["metrics"]
    assert report["source"]["kind"] == "file"
    assert report["source"]["dataset_kind"] == "vector"
    assert metrics["crs"] == "EPSG:4326"
    assert metrics["vector"]["feature_count"] == 4
    assert metrics["vector"]["invalid_count"] == 0
    assert metrics["vector"]["empty_count"] == 0
    assert metrics["bbox"]["minx"] == pytest.approx(10.0)
    assert metrics["vector"]["area_stats"]["sum"] > 0
    assert metrics["vector"]["length_stats"] is None
    assert report["qc_status"] == "ok"


def test_null_attributes_and_invalid_geometry_are_counted():
    metrics = qc_report(str(FIXTURES / "dirty.gpkg"), QcContext())["metrics"]
    assert metrics["vector"]["invalid_count"] == 1
    assert metrics["vector"]["null_counts"]["name"] == 1


def test_ogr_is_the_authority_on_dimensionality():
    flat = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext())["metrics"]["vector"]
    three_d = qc_report(str(FIXTURES / "aoi_3d.gpkg"), QcContext())["metrics"]["vector"]
    assert flat["has_z"] is False
    assert three_d["has_z"] is True


def test_duplicate_ids_are_counted_only_when_a_column_is_named():
    default = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext())["metrics"]["vector"]
    assert default["duplicate_id_count"] is None
    named = qc_report(str(FIXTURES / "aoi.gpkg"), QcContext(id_column="id"))["metrics"]["vector"]
    assert named["duplicate_id_count"] == 0


def test_a_geoparquet_file_uses_the_read_parquet_branch():
    """export --format parquet exists, so QC must read what it writes."""
    report = qc_report(str(FIXTURES / "aoi.parquet"), QcContext())
    assert report["metrics"]["vector"]["feature_count"] == 4
    assert report["metrics"]["crs"] == "EPSG:4326"


def test_a_missing_file_is_a_gis_error():
    with pytest.raises(GisError) as caught:
        qc_report("/nowhere/missing.gpkg", QcContext())
    assert caught.value.code == INPUT_NOT_FOUND
```

- [ ] **Step 4: Run it and watch it fail**

Run: `uv run pytest tests/test_qc_file.py -v`
Expected: FAIL — `ImportError: cannot import name 'qc_report'`.

- [ ] **Step 5: Add the reader helper to `llm_gis/duck.py`**

Append, leaving `describe` untouched so Phase 2 behaviour does not move:

```python
PARQUET_SUFFIXES = {".parquet", ".geoparquet", ".pq"}


def reader_sql(uri: str) -> str:
    """The table function that reads this source, chosen by extension.

    The agent GDAL build has no Parquet driver, so ST_Read cannot open a
    Parquet file at all; read_parquet cannot open a GeoPackage. One of the
    two is always right and the extension says which.
    """
    suffix = Path(uri.split("?")[0]).suffix.lower()
    return "read_parquet(?)" if suffix in PARQUET_SUFFIXES else "ST_Read(?)"
```

If Step 1 case A failed, `reader_sql` takes the path directly and returns a literal instead: `f"ST_Read('{uri.replace(chr(39), chr(39) * 2)}')"`, and callers stop passing the `[uri]` parameter list for that branch.

- [ ] **Step 6: Write `llm_gis/qc_collect.py`**

```python
"""All the I/O behind QC. One normalised metrics dict out, whatever the source.

Vector aggregates run in SQL rather than in memory, so QC over a large export
costs a scan, not a load. GDAL keeps authority over declared dimensionality,
which DuckDB's reader does not reliably preserve.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import duckdb

from llm_gis.common import (
    crs_text_from_ogr_coordinate_system,
    normalize_crs,
    run_command,
)
from llm_gis.duck import _crs_from_geo_metadata, _geo_metadata, connect, reader_sql
from llm_gis.errors import COMMAND_FAILED, GisError

RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}


def _ogr_layer(path: Path) -> dict[str, Any]:
    payload = json.loads(run_command(["ogrinfo", "-json", "-ro", str(path)]))
    return (payload.get("layers") or [{}])[0]


def _ogr_facts(path: Path) -> dict[str, Any]:
    """Declared CRS, geometry type and dimensionality, from GDAL's own reading."""
    layer = _ogr_layer(path)
    field = (layer.get("geometryFields") or [{}])[0]
    declared = field.get("type") or ""
    return {
        "crs": normalize_crs(crs_text_from_ogr_coordinate_system(field.get("coordinateSystem") or {})),
        "declared_geometry_type": declared or None,
        "has_z": "3D" in declared or declared.endswith("Z") or declared.endswith("ZM"),
        "has_m": "Measured" in declared or declared.endswith("M"),
    }


def _geometry_column(connection: duckdb.DuckDBPyConnection, reader: str, uri: str) -> str | None:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {reader}", [uri]).fetchall()
    for name, type_, *_ in rows:
        if str(type_).upper().startswith("GEOMETRY"):
            return name
    return None


def _columns(connection: duckdb.DuckDBPyConnection, reader: str, uri: str) -> list[str]:
    rows = connection.execute(f"DESCRIBE SELECT * FROM {reader}", [uri]).fetchall()
    return [name for name, *_ in rows]


def _dimension_stats(geometry_types: dict[str, int]) -> str:
    """Area for polygons, length for lines, neither for points."""
    dominant = max(geometry_types, key=geometry_types.get) if geometry_types else ""
    upper = dominant.upper()
    if "POLYGON" in upper:
        return "area"
    if "LINE" in upper:
        return "length"
    return "none"


def _vector_aggregates(
    connection: duckdb.DuckDBPyConnection,
    reader: str,
    uri: str,
    geometry: str,
    attributes: list[str],
    id_column: str | None,
) -> dict[str, Any]:
    g = f'"{geometry}"'
    null_terms = ", ".join(
        f'count(*) FILTER (WHERE "{c}" IS NULL) AS "null_{c}"' for c in attributes
    )
    duplicate_term = (
        f'count(*) - count(DISTINCT "{id_column}") AS duplicate_id_count'
        if id_column
        else "NULL AS duplicate_id_count"
    )
    statement = f"""
        SELECT count(*) AS feature_count,
               count(*) FILTER (WHERE {g} IS NULL OR ST_IsEmpty({g})) AS empty_count,
               count(*) FILTER (WHERE {g} IS NOT NULL AND NOT ST_IsValid({g})) AS invalid_count,
               min(ST_XMin({g})) AS minx, min(ST_YMin({g})) AS miny,
               max(ST_XMax({g})) AS maxx, max(ST_YMax({g})) AS maxy,
               min(ST_Area({g})) AS area_min, max(ST_Area({g})) AS area_max,
               avg(ST_Area({g})) AS area_mean, sum(ST_Area({g})) AS area_sum,
               min(ST_Length({g})) AS length_min, max(ST_Length({g})) AS length_max,
               avg(ST_Length({g})) AS length_mean, sum(ST_Length({g})) AS length_sum,
               {duplicate_term}
               {"," + null_terms if null_terms else ""}
        FROM {reader}
    """
    cursor = connection.execute(statement, [uri])
    names = [d[0] for d in cursor.description]
    return dict(zip(names, cursor.fetchone()))


def _geometry_histogram(
    connection: duckdb.DuckDBPyConnection, reader: str, uri: str, geometry: str
) -> dict[str, int]:
    rows = connection.execute(
        f'SELECT ST_GeometryType("{geometry}") AS t, count(*) FROM {reader} '
        f'WHERE "{geometry}" IS NOT NULL GROUP BY 1',
        [uri],
    ).fetchall()
    return {str(t): int(n) for t, n in rows}


def _stats_block(row: dict[str, Any], prefix: str) -> dict[str, float] | None:
    if row.get(f"{prefix}_sum") is None:
        return None
    return {
        "min": row[f"{prefix}_min"],
        "max": row[f"{prefix}_max"],
        "mean": row[f"{prefix}_mean"],
        "sum": row[f"{prefix}_sum"],
    }


def file_vector_metrics(path: Path, id_column: str | None) -> dict[str, Any]:
    uri = str(path)
    reader = reader_sql(uri)
    is_parquet = reader.startswith("read_parquet")
    connection = connect()
    try:
        geometry = _geometry_column(connection, reader, uri)
        if geometry is None:
            raise GisError(
                COMMAND_FAILED,
                f"No geometry column found in {uri}",
                "QC over a vector source needs a geometry column; use inspect for a plain table",
            )
        attributes = [c for c in _columns(connection, reader, uri) if c != geometry]
        row = _vector_aggregates(connection, reader, uri, geometry, attributes, id_column)
        histogram = _geometry_histogram(connection, reader, uri, geometry)
    except duckdb.Error as error:
        raise GisError(
            COMMAND_FAILED,
            f"DuckDB could not read {uri} for QC",
            "Confirm the file is a readable vector dataset or GeoParquet",
            {"duckdb_error": str(error)},
        ) from error

    if is_parquet:
        crs = _crs_from_geo_metadata(_geo_metadata(connection, uri))
        declared, has_z, has_m = None, None, None
    else:
        facts = _ogr_facts(path)
        crs = facts["crs"]
        declared, has_z, has_m = facts["declared_geometry_type"], facts["has_z"], facts["has_m"]

    dimension = _dimension_stats(histogram)
    bbox = (
        None
        if row["minx"] is None
        else {"minx": row["minx"], "miny": row["miny"], "maxx": row["maxx"], "maxy": row["maxy"]}
    )
    return {
        "crs": crs,
        "bbox": bbox,
        "vector": {
            "feature_count": int(row["feature_count"]),
            "geometry_types": histogram,
            "declared_geometry_type": declared,
            "empty_count": int(row["empty_count"]),
            "invalid_count": int(row["invalid_count"]),
            "has_z": has_z,
            "has_m": has_m,
            "area_stats": _stats_block(row, "area") if dimension == "area" else None,
            "length_stats": _stats_block(row, "length") if dimension == "length" else None,
            "null_counts": {c: int(row[f"null_{c}"]) for c in attributes},
            "duplicate_id_count": None if row["duplicate_id_count"] is None else int(row["duplicate_id_count"]),
            "id_column": id_column,
        },
        "raster": None,
    }


def file_raster_metrics(path: Path, exact_stats: bool) -> dict[str, Any]:
    """gdalinfo with PAM disabled: a .aux.xml write beside a read-only source would fail."""
    flag = "-stats" if exact_stats else "-approx_stats"
    env = {**os.environ, "GDAL_PAM_ENABLED": "NO"}
    payload = json.loads(run_command(["gdalinfo", "-json", flag, str(path)], env=env))
    size = payload.get("size") or [None, None]
    transform = payload.get("geoTransform") or [0, None, 0, 0, 0, None]
    corners = payload.get("cornerCoordinates", {})
    xs = [c[0] for c in corners.values() if c]
    ys = [c[1] for c in corners.values() if c]
    bands = []
    for band in payload.get("bands", []):
        metadata = (band.get("metadata") or {}).get("", {})
        valid_percent = metadata.get("STATISTICS_VALID_PERCENT")
        bands.append(
            {
                "index": band.get("band"),
                "nodata": band.get("noDataValue"),
                "min": band.get("minimum"),
                "max": band.get("maximum"),
                "mean": band.get("mean"),
                "percent_nodata": None if valid_percent is None else 100.0 - float(valid_percent),
            }
        )
    return {
        "crs": normalize_crs((payload.get("coordinateSystem") or {}).get("wkt")),
        "bbox": None if not xs else {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)},
        "vector": None,
        "raster": {
            "width": size[0],
            "height": size[1],
            "band_count": len(bands),
            "resolution": {"x": transform[1], "y": abs(transform[5]) if transform[5] else None},
            "bands": bands,
            "stats_mode": "exact" if exact_stats else "approximate",
        },
    }


def file_metrics(path: Path, id_column: str | None, exact_stats: bool) -> tuple[dict, dict]:
    """Dispatch on extension, then collect. Returns (source, metrics)."""
    kind = "raster" if path.suffix.lower() in RASTER_SUFFIXES else "vector"
    metrics = (
        file_raster_metrics(path, exact_stats)
        if kind == "raster"
        else file_vector_metrics(path, id_column)
    )
    return {"kind": "file", "ref": str(path), "dataset_kind": kind}, metrics
```

- [ ] **Step 7: Add dispatch to `llm_gis/qc.py`**

Append:

```python
def resolve_source(ref: str) -> dict[str, str]:
    """A path if one exists on disk, otherwise schema.table."""
    path = Path(ref)
    if path.exists():
        return {"kind": "file", "ref": ref}
    if "." in ref and "/" not in ref:
        schema, table = ref.split(".", 1)
        return {"kind": "postgis_table", "ref": ref, "schema": schema, "table": table}
    raise GisError(
        INPUT_NOT_FOUND,
        f"No file at {ref}, and it is not a schema.table reference",
        "Pass a path under /data, or a table like analysis_<ingest_id>.result",
    )


def qc_report(ref: str, context: QcContext, *, exact_stats: bool = False) -> dict[str, Any]:
    """Collect metrics for one source and judge them against the declared context."""
    resolved = resolve_source(ref)
    if resolved["kind"] != "file":
        raise GisError(
            INPUT_NOT_FOUND,
            f"QC over PostGIS tables is not wired yet: {ref}",
            "Pass a file path",
        )
    source, metrics = qc_collect.file_metrics(Path(ref), context.id_column, exact_stats)
    return build_report(source, metrics, context)
```

with these imports added at the top of `qc.py`:

```python
from pathlib import Path

from llm_gis import qc_collect
from llm_gis.errors import CRS_MISSING, CRS_SUSPICIOUS, INPUT_NOT_FOUND, GisError
```

The `postgis_table` branch is a placeholder only until Task 4 replaces it, and Task 4's first step is to delete it.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_qc_file.py -v`
Expected: PASS, 6 tests.

If `test_ogr_is_the_authority_on_dimensionality` fails because GeoPandas wrote the 3D layer as `Polygon` rather than `3D Polygon`, print `ogrinfo -json tests/fixtures/aoi_3d.gpkg | head -40`, read the actual `geometryFields[0].type` string, and widen `_ogr_facts`'s `has_z` test to match what GDAL really prints. Do not weaken the assertion.

- [ ] **Step 9: Run the whole suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add llm_gis/qc_collect.py llm_gis/qc.py llm_gis/duck.py tests/test_qc_file.py tests/fixtures/
git commit -m "feat: QC file collectors for vector, raster and GeoParquet"
```

Record the Step 1 verification answers in the commit body: whether `ST_Read(?)` parameterises, what the geometry column is called, and whether `ST_HasZ` exists.

---

### Task 3: PostGIS collectors

**Files:**
- Modify: `llm_gis/qc_collect.py`, `llm_gis/qc.py`
- Test: `tests/live/test_qc_postgis.py`

**Interfaces:**
- Consumes: `file_metrics`, `build_report`, `QcContext`, `resolve_source`.
- Produces: `qc_collect.table_metrics(schema: str, table: str, id_column: str | None) -> tuple[dict, dict]`; `qc_report` gaining its table branch.

- [ ] **Step 1: Write the failing live test**

Create `tests/live/test_qc_postgis.py`:

```python
"""QC over a real PostGIS table. Requires the compose stack: bin/test -m live."""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest

from llm_gis.common import db_connect, sanitize_identifier
from llm_gis.ingest_vector import ingest_vector
from llm_gis.qc import QcContext, qc_report

FIXTURES = Path(__file__).parent.parent / "fixtures"
TABLE_NAME = "aoi_qc"


@pytest.fixture
def ingested(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(incoming))
    source = incoming / "aoi.gpkg"
    shutil.copy2(FIXTURES / "aoi.gpkg", source)

    report = ingest_vector(
        input_path=source, table=TABLE_NAME, ingest_id=None,
        src_crs=None, dst_crs=None, schema=None,
    )
    yield report["schema"], TABLE_NAME

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE;").format(
                    psycopg.sql.Identifier(report["schema"])
                )
            )


@pytest.mark.live
def test_qc_over_a_postgis_table(ingested):
    schema, table = ingested
    report = qc_report(f"{schema}.{table}", QcContext())
    metrics = report["metrics"]
    assert report["source"]["kind"] == "postgis_table"
    assert metrics["vector"]["feature_count"] == 4
    assert metrics["vector"]["invalid_count"] == 0
    assert metrics["crs"] == "EPSG:4326"
    assert metrics["bbox"]["minx"] == pytest.approx(10.0)
    assert metrics["vector"]["duplicate_id_count"] == 0


@pytest.mark.live
def test_a_metric_operation_on_a_geographic_table_warns(ingested):
    schema, table = ingested
    report = qc_report(f"{schema}.{table}", QcContext(metric_op=True))
    assert "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION" in [w["code"] for w in report["warnings"]]


@pytest.mark.live
def test_a_missing_table_is_a_gis_error():
    from llm_gis.errors import TABLE_NOT_FOUND, GisError

    with pytest.raises(GisError) as caught:
        qc_report("raw_nope.nothing", QcContext())
    assert caught.value.code == TABLE_NOT_FOUND
```

- [ ] **Step 2: Run it and watch it fail**

Run: `bin/test -m live tests/live/test_qc_postgis.py`
Expected: FAIL — `GisError: QC over PostGIS tables is not wired yet`.

- [ ] **Step 3: Add the table collectors to `llm_gis/qc_collect.py`**

Three queries: the column list, the aggregate, the geometry histogram.

```python
from psycopg import sql

from llm_gis.common import db_connect
from llm_gis.errors import TABLE_NOT_FOUND


def _table_columns(cursor, schema: str, table: str) -> tuple[list[str], bool]:
    cursor.execute(
        """
        SELECT column_name, udt_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    rows = cursor.fetchall()
    if not rows:
        raise GisError(
            TABLE_NOT_FOUND,
            f"Table {schema}.{table} does not exist or is not visible to this role",
            "Run list-ingestions to see available schemas",
        )
    attributes = [name for name, udt in rows if udt not in {"geometry", "geography", "raster"}]
    is_raster = any(udt == "raster" for _, udt in rows)
    return attributes, is_raster


def _table_vector_metrics(cursor, schema: str, table: str, attributes: list[str], id_column: str | None) -> dict:
    relation = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    null_terms = sql.SQL(", ").join(
        sql.SQL("count(*) FILTER (WHERE {} IS NULL)").format(sql.Identifier(c)) for c in attributes
    )
    duplicate_term = (
        sql.SQL("count(*) - count(DISTINCT {})").format(sql.Identifier(id_column))
        if id_column
        else sql.SQL("NULL::bigint")
    )
    statement = sql.SQL(
        """
        SELECT count(*),
               count(*) FILTER (WHERE geom IS NULL OR ST_IsEmpty(geom)),
               count(*) FILTER (WHERE geom IS NOT NULL AND NOT ST_IsValid(geom)),
               ST_XMin(ST_Extent(geom)), ST_YMin(ST_Extent(geom)),
               ST_XMax(ST_Extent(geom)), ST_YMax(ST_Extent(geom)),
               max(ST_SRID(geom)),
               bool_or(ST_Zmflag(geom) IN (2, 3)),
               bool_or(ST_Zmflag(geom) IN (1, 3)),
               min(ST_Area(geom)), max(ST_Area(geom)), avg(ST_Area(geom)), sum(ST_Area(geom)),
               min(ST_Length(geom)), max(ST_Length(geom)), avg(ST_Length(geom)), sum(ST_Length(geom)),
               {duplicates}{null_head}{nulls}
        FROM {relation}
        """
    ).format(
        duplicates=duplicate_term,
        null_head=sql.SQL(", ") if attributes else sql.SQL(""),
        nulls=null_terms if attributes else sql.SQL(""),
        relation=relation,
    )
    cursor.execute(statement)
    values = cursor.fetchone()
    keys = [
        "feature_count", "empty_count", "invalid_count", "minx", "miny", "maxx", "maxy",
        "srid", "has_z", "has_m",
        "area_min", "area_max", "area_mean", "area_sum",
        "length_min", "length_max", "length_mean", "length_sum",
        "duplicate_id_count",
    ]
    row = dict(zip(keys, values))
    row["null_counts"] = {c: int(v) for c, v in zip(attributes, values[len(keys):])}
    return row


def _table_geometry_histogram(cursor, schema: str, table: str) -> dict[str, int]:
    cursor.execute(
        sql.SQL(
            "SELECT GeometryType(geom), count(*) FROM {}.{} WHERE geom IS NOT NULL GROUP BY 1"
        ).format(sql.Identifier(schema), sql.Identifier(table))
    )
    return {str(t): int(n) for t, n in cursor.fetchall()}


def _table_raster_metrics(cursor, schema: str, table: str) -> dict:
    """Structure only. Pixel statistics over a tiled raster table are deferred."""
    cursor.execute(
        """
        SELECT srid, scale_x, scale_y, num_bands,
               ST_XMin(extent), ST_YMin(extent), ST_XMax(extent), ST_YMax(extent)
        FROM raster_columns
        WHERE r_table_schema = %s AND r_table_name = %s
        """,
        (schema, table),
    )
    row = cursor.fetchone()
    if row is None:
        raise GisError(
            TABLE_NOT_FOUND,
            f"{schema}.{table} has a raster column but no raster_columns entry",
            "Re-run ingest-raster for this table",
        )
    srid, scale_x, scale_y, num_bands, minx, miny, maxx, maxy = row
    return {
        "crs": f"EPSG:{srid}" if srid else None,
        "bbox": None if minx is None else {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
        "vector": None,
        "raster": {
            "width": None,
            "height": None,
            "band_count": num_bands,
            "resolution": {"x": scale_x, "y": abs(scale_y) if scale_y else None},
            "bands": [],
            "stats_mode": "none",
        },
    }


def table_metrics(schema: str, table: str, id_column: str | None) -> tuple[dict, dict]:
    """Vector tables fully, raster tables structurally. Returns (source, metrics)."""
    with db_connect() as conn:
        with conn.cursor() as cursor:
            attributes, is_raster = _table_columns(cursor, schema, table)
            if is_raster:
                metrics = _table_raster_metrics(cursor, schema, table)
                kind = "raster"
            else:
                resolved_id = id_column or ("fid" if "fid" in attributes else None)
                row = _table_vector_metrics(cursor, schema, table, attributes, resolved_id)
                histogram = _table_geometry_histogram(cursor, schema, table)
                dimension = _dimension_stats(histogram)
                metrics = {
                    "crs": f"EPSG:{row['srid']}" if row["srid"] else None,
                    "bbox": None if row["minx"] is None else {
                        "minx": row["minx"], "miny": row["miny"],
                        "maxx": row["maxx"], "maxy": row["maxy"],
                    },
                    "vector": {
                        "feature_count": int(row["feature_count"]),
                        "geometry_types": histogram,
                        "declared_geometry_type": None,
                        "empty_count": int(row["empty_count"]),
                        "invalid_count": int(row["invalid_count"]),
                        "has_z": row["has_z"],
                        "has_m": row["has_m"],
                        "area_stats": _stats_block(row, "area") if dimension == "area" else None,
                        "length_stats": _stats_block(row, "length") if dimension == "length" else None,
                        "null_counts": row["null_counts"],
                        "duplicate_id_count": None if row["duplicate_id_count"] is None else int(row["duplicate_id_count"]),
                        "id_column": resolved_id,
                    },
                    "raster": None,
                }
                kind = "vector"
    return {"kind": "postgis_table", "ref": f"{schema}.{table}", "dataset_kind": kind}, metrics
```

- [ ] **Step 4: Replace the placeholder branch in `llm_gis/qc.py`**

```python
def qc_report(ref: str, context: QcContext, *, exact_stats: bool = False) -> dict[str, Any]:
    """Collect metrics for one source and judge them against the declared context."""
    resolved = resolve_source(ref)
    if resolved["kind"] == "file":
        source, metrics = qc_collect.file_metrics(Path(ref), context.id_column, exact_stats)
    else:
        source, metrics = qc_collect.table_metrics(
            resolved["schema"], resolved["table"], context.id_column
        )
    return build_report(source, metrics, context)
```

- [ ] **Step 5: Run the live tests**

Run: `docker compose up -d db && bin/test -m live tests/live/test_qc_postgis.py`
Expected: PASS, 3 tests.

- [ ] **Step 6: Run the default suite**

Run: `uv run pytest`
Expected: PASS. The table collectors are untouched by the offline run.

- [ ] **Step 7: Commit**

```bash
git add llm_gis/qc_collect.py llm_gis/qc.py tests/live/test_qc_postgis.py
git commit -m "feat: QC collectors for PostGIS vector and raster tables"
```

---

### Task 4: The `qc` command

**Files:**
- Modify: `llm_gis/cli.py`, `docs/llm/OUTPUT_SCHEMA.md`
- Create: `bin/qc`
- Test: `tests/test_qc_cli.py`

**Interfaces:**
- Consumes: `qc.qc_report`, `qc.QcContext`, `qc.resolve_source`, `qc_collect.file_metrics`, `qc_collect.table_metrics`.
- Produces: the `qc` subcommand and `bin/qc`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_qc_cli.py`:

```python
"""The qc command's envelope and flag handling."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_gis.cli import app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))


def _run_ok(args: list[str]) -> dict:
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_qc_carries_the_standard_envelope():
    payload = _run_ok(["qc", str(FIXTURES / "aoi.gpkg")])
    assert payload["status"] == "ok"
    assert payload["command"] == "qc"
    assert payload["qc_status"] == "ok"
    assert payload["metrics"]["vector"]["feature_count"] == 4


def test_a_warning_does_not_change_the_transport_status():
    """status is the envelope: the command ran. qc_status is the verdict."""
    payload = _run_ok(["qc", str(FIXTURES / "aoi.gpkg"), "--metric-op"])
    assert payload["status"] == "ok"
    assert payload["qc_status"] == "warning"
    assert payload["warnings"][0]["code"] == "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION"


def test_compare_to_a_disjoint_file_warns():
    payload = _run_ok([
        "qc", str(FIXTURES / "aoi.gpkg"), "--compare-to", str(FIXTURES / "dirty.gpkg"),
    ])
    codes = [w["code"] for w in payload["warnings"]]
    assert "RESULT_BBOX_DISJOINT_FROM_INPUT" not in codes


def test_a_missing_input_exits_one_with_json_on_stderr():
    result = CliRunner().invoke(app, ["qc", "/nowhere/missing.gpkg"])
    assert result.exit_code == 1


def test_raster_qc_reports_bands_without_writing_a_sidecar(tmp_path):
    source = tmp_path / "elevation.tif"
    source.write_bytes((FIXTURES / "elevation.tif").read_bytes())
    payload = _run_ok(["qc", str(source)])
    assert payload["metrics"]["raster"]["band_count"] == 1
    assert payload["metrics"]["raster"]["stats_mode"] == "approximate"
    assert not (tmp_path / "elevation.tif.aux.xml").exists()
```

That last test is the read-only-mount guarantee, verified rather than asserted in prose.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_qc_cli.py -v`
Expected: FAIL — `No such command 'qc'`, exit code 2.

- [ ] **Step 3: Add the command to `llm_gis/cli.py`**

Import `from llm_gis.qc import QcContext, qc_report` and `from llm_gis import qc_collect`, then:

```python
@app.command("qc")
@handle_errors
def qc_cmd(
    ref: str = typer.Argument(..., help="File path, or schema.table"),
    expect_non_empty: bool = typer.Option(False, "--expect-non-empty", help="Treat an empty result as a problem"),
    metric_op: bool = typer.Option(False, "--metric-op", help="This data feeds areas, lengths or distances"),
    compare_to: str | None = typer.Option(None, "--compare-to", help="File or table whose extent this should overlap"),
    id_column: str | None = typer.Option(None, "--id-column", help="Column to check for duplicate identifiers"),
    exact_stats: bool = typer.Option(False, "--exact-stats", help="Full raster pixel scan instead of an approximation"),
) -> None:
    """Deterministic metrics and warnings for a dataset or a table."""
    context = QcContext(
        expect_non_empty=expect_non_empty,
        metric_op=metric_op,
        id_column=id_column,
        reference=reference_for(compare_to) if compare_to else None,
    )
    _emit("qc", qc_report(ref, context, exact_stats=exact_stats))
```

Add `reference_for` to `llm_gis/qc.py`, since export needs it too:

```python
def reference_for(ref: str) -> dict[str, Any]:
    """The CRS and extent of a comparison source, collected the same way as the subject."""
    resolved = resolve_source(ref)
    if resolved["kind"] == "file":
        _, metrics = qc_collect.file_metrics(Path(ref), None, False)
    else:
        _, metrics = qc_collect.table_metrics(resolved["schema"], resolved["table"], None)
    return {"ref": ref, "crs": metrics["crs"], "bbox": metrics["bbox"]}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_qc_cli.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Add the wrapper**

```bash
cat > bin/qc <<'SH'
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/_env.sh"
docker compose --progress quiet run --rm agent uv run --quiet llm-gis qc "$@"
SH
chmod +x bin/qc
```

- [ ] **Step 6: Document it in `docs/llm/OUTPUT_SCHEMA.md`**

A `bin/qc` section is mandatory — `test_output_schema_lists_every_bin_command` fails without it. Add, alongside the existing per-command sections:

```markdown
## bin/qc

| Key | Type | Meaning |
|---|---|---|
| `qc_status` | string | `"ok"` or `"warning"`. The verdict on the data. Distinct from `status`, which reports only that the command ran. |
| `source` | object | `kind` (`file` or `postgis_table`), `ref`, `dataset_kind` (`vector` or `raster`). |
| `metrics` | object | `crs`, `bbox`, and one of `vector` or `raster`; the other is `null`. |
| `checks` | array | Every check: `code`, `severity`, `result` (`pass`, `warn`, `not_evaluated`), `message`. |
| `warnings` | array | The `warn` subset, as `code`, `message`, `severity`. |
| `created_at` | string | UTC timestamp. |

A `result` of `not_evaluated` means the check was skipped for want of declared context, not that it passed. `CRS_MISSING` and `CRS_SUSPICIOUS` appear here as advisory warnings with exit code 0; the same codes raised by `ingest-vector` and `ingest-raster` are fatal errors with exit code 1. A code inside `warnings` is an observation; a code inside a `{"status": "error"}` object is a refusal.
```

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest`
Expected: PASS, including `test_output_schema_lists_every_bin_command`.

- [ ] **Step 8: Commit**

```bash
git add llm_gis/cli.py llm_gis/qc.py bin/qc tests/test_qc_cli.py docs/llm/OUTPUT_SCHEMA.md
git commit -m "feat: bin/qc command"
```

---

### Task 5: QC attached to export

**Files:**
- Modify: `llm_gis/exporter.py`, `llm_gis/cli.py`, `docs/llm/OUTPUT_SCHEMA.md`
- Test: `tests/test_qc_export.py`, `tests/live/test_qc_postgis.py`

**Interfaces:**
- Consumes: `qc.qc_report`, `qc.QcContext`, `qc.reference_for`.
- Produces: `export_result(..., qc: bool = True, compare_to: str | None = None)`; a `qc` key on the export result.

- [ ] **Step 1: Write the failing test**

Create `tests/test_qc_export.py`. `export_result` needs a database, so this covers the QC wiring in isolation with a stubbed writer.

```python
"""Export attaches QC to what it wrote, and resolves its reference in the
documented order: --compare-to, then --table, then nothing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from llm_gis import exporter

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def written(monkeypatch, tmp_path):
    """Skip the ogr2ogr call; put a real GeoPackage where export would write one."""
    destination = tmp_path / "result.gpkg"

    def fake_run_command(cmd, **kwargs):
        shutil.copy2(FIXTURES / "aoi.gpkg", destination)
        return ""

    monkeypatch.setattr(exporter, "run_command", fake_run_command)
    return destination


def test_export_attaches_a_qc_block_by_default(written):
    result = exporter.export_result(written, "gpkg", table="raw_x.aoi", qc=True)
    assert result["qc"]["metrics"]["vector"]["feature_count"] == 4
    assert result["feature_count"] == 4


def test_no_qc_omits_the_block(written):
    result = exporter.export_result(written, "gpkg", table="raw_x.aoi", qc=False)
    assert "qc" not in result


def test_a_sql_export_without_compare_to_cannot_check_the_bbox(written, monkeypatch):
    monkeypatch.setattr(exporter, "reference_for", lambda ref: pytest.fail("must not be called"))
    result = exporter.export_result(written, "gpkg", sql_query="SELECT 1", qc=True)
    check = next(
        c for c in result["qc"]["checks"] if c["code"] == "RESULT_BBOX_DISJOINT_FROM_INPUT"
    )
    assert check["result"] == "not_evaluated"


def test_compare_to_wins_over_the_source_table(written, monkeypatch):
    seen = []

    def fake_reference_for(ref):
        seen.append(ref)
        return {"ref": ref, "crs": "EPSG:4326",
                "bbox": {"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0}}

    monkeypatch.setattr(exporter, "reference_for", fake_reference_for)
    result = exporter.export_result(
        written, "gpkg", table="raw_x.aoi", compare_to="raw_x.parcels", qc=True
    )
    assert seen == ["raw_x.parcels"]
    assert "RESULT_BBOX_DISJOINT_FROM_INPUT" in [w["code"] for w in result["qc"]["warnings"]]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_qc_export.py -v`
Expected: FAIL — `export_result() got an unexpected keyword argument 'qc'`.

- [ ] **Step 3: Wire QC into `llm_gis/exporter.py`**

Add `from llm_gis.qc import QcContext, qc_report, reference_for` at the top, extend the signature, and append the block before the return:

```python
def export_result(
    output_path: Path,
    output_format: str,
    *,
    table: str | None = None,
    sql_query: str | None = None,
    qc: bool = True,
    compare_to: str | None = None,
) -> dict:
```

```python
    result = {
        "output_path": str(output_path),
        "output_format": fmt,
        "table": table,
        "sql": sql_query,
        "feature_count": feature_count,
        "crs": crs,
    }
    if qc:
        result["qc"] = qc_report(str(output_path), QcContext(reference=_export_reference(table, compare_to)))
    return result
```

and the resolution order as its own function, so the rule is readable in one place:

```python
def _export_reference(table: str | None, compare_to: str | None) -> dict | None:
    """--compare-to, else the source table, else nothing.

    A --table export compared against its own table is close to a tautology:
    it catches a reprojection or driver fault and nothing else. A --sql export
    has no inferable input, which is why --compare-to exists.
    """
    if compare_to:
        return reference_for(compare_to)
    if table:
        return reference_for(table)
    return None
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_qc_export.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the flags to `llm_gis/cli.py`**

```python
@app.command("export")
@handle_errors
def export_cmd(
    output_path: Path = typer.Argument(..., help="Output path under /data/outgoing"),
    output_format: str = typer.Option(..., "--format", help="gpkg, geojson or parquet"),
    table: str | None = typer.Option(None, help="Table name like analysis_...result"),
    sql_query: str | None = typer.Option(None, "--sql", help="Custom SQL query"),
    qc: bool = typer.Option(True, "--qc/--no-qc", help="Attach a QC block to the result"),
    compare_to: str | None = typer.Option(None, "--compare-to", help="Table or file whose extent the result should overlap"),
) -> None:
    _emit(
        "export",
        export_result(
            output_path, output_format, table=table, sql_query=sql_query,
            qc=qc, compare_to=compare_to,
        ),
    )
```

- [ ] **Step 6: Extend the live test**

Append to `tests/live/test_qc_postgis.py`:

```python
@pytest.mark.live
def test_export_attaches_qc_over_the_real_file(ingested, tmp_path):
    from llm_gis.exporter import export_result

    schema, table = ingested
    output = Path("/data/outgoing") / "_live_test_qc" / "aoi.gpkg"
    try:
        result = export_result(output, "gpkg", table=f"{schema}.{table}")
        assert result["qc"]["metrics"]["vector"]["feature_count"] == 4
        assert result["qc"]["qc_status"] == "ok"
        bbox_check = next(
            c for c in result["qc"]["checks"] if c["code"] == "RESULT_BBOX_DISJOINT_FROM_INPUT"
        )
        assert bbox_check["result"] == "pass"
    finally:
        shutil.rmtree(output.parent, ignore_errors=True)
```

Run: `bin/test -m live tests/live/test_qc_postgis.py`
Expected: PASS, 4 tests.

- [ ] **Step 7: Update the export section of `docs/llm/OUTPUT_SCHEMA.md`**

Add to the existing `bin/export` key table:

```markdown
| `qc` | object | The full `bin/qc` result over the file just written. Present unless `--no-qc` was given. |
```

and a sentence below it: the extent comparison uses `--compare-to` when given, otherwise the `--table` source, and is `not_evaluated` for a `--sql` export with no `--compare-to`.

- [ ] **Step 8: Run the whole suite**

Run: `uv run pytest && bin/test -m live`
Expected: PASS on both.

- [ ] **Step 9: Commit**

```bash
git add llm_gis/exporter.py llm_gis/cli.py tests/test_qc_export.py tests/live/test_qc_postgis.py docs/llm/OUTPUT_SCHEMA.md
git commit -m "feat: attach QC to export output"
```

---

### Task 6: Operator documentation

Documentation ships with the phase, per O22. No code.

**Files:**
- Modify: `README.md`, `AGENTS.md`, `.claude/skills/hot-start/SKILL.md`

- [ ] **Step 1: Read what is there**

Run: `grep -n "bin/export" README.md AGENTS.md .claude/skills/hot-start/SKILL.md`
Expected: the command tables that need a `bin/qc` row, in each file's own style.

- [ ] **Step 2: Add the command row**

In each command table, following the existing formatting:

```markdown
| `bin/qc <path-or-table> [--expect-non-empty] [--metric-op] [--compare-to <ref>] [--id-column <c>] [--exact-stats]` | Deterministic metrics and warnings for a dataset or table |
```

- [ ] **Step 3: Add the warning-code table to `.claude/skills/hot-start/SKILL.md`**

Under a new `## Quality control` heading:

```markdown
QC reports metrics and, where the caller declared enough context, warnings.

| Code | Meaning |
|---|---|
| `CRS_MISSING` | No CRS on the dataset |
| `CRS_SUSPICIOUS` | The CRS does not match the extent (lon/lat values in a projected CRS, or the reverse) |
| `GEOGRAPHIC_CRS_FOR_METRIC_OPERATION` | Areas or distances requested from degree-based coordinates. Needs `--metric-op` |
| `EMPTY_RESULT_UNEXPECTED` | Zero features where features were expected. Needs `--expect-non-empty` |
| `RESULT_BBOX_DISJOINT_FROM_INPUT` | The result lies nowhere near its input. Needs `--compare-to` |

A check `result` of `not_evaluated` means it was skipped for want of context, not that it passed. Pass the flags when you know the answer, and read `not_evaluated` as "nobody checked".

`CRS_MISSING` and `CRS_SUSPICIOUS` are advisory in a QC result (exit 0) and fatal in `ingest-vector` / `ingest-raster` (exit 1). Same names, different force.

`export` runs QC over what it wrote unless `--no-qc` is given. For a `--sql` export, pass `--compare-to <source table>` or the extent check cannot run.
```

- [ ] **Step 4: Update the standard workflow in `.claude/skills/hot-start/SKILL.md`**

Change step 7 of the numbered workflow to note that export returns a QC block, and add step 8: read `qc.warnings` and report anything there to the human in plain terms before declaring the job done.

- [ ] **Step 5: Run the suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add README.md AGENTS.md .claude/skills/hot-start/SKILL.md
git commit -m "docs: bin/qc and the QC warning codes"
```

---

### Task 7: Field test

The phase is not done until a real job runs end to end. This is the plan's last gate and it produces a report, not code.

- [ ] **Step 1: Bring the stack up**

Run: `docker compose up -d --build && bin/doctor`
Expected: JSON with database connectivity and tool versions, exit 0.

- [ ] **Step 2: Run a real job through the operator workflow**

Use a real dataset from `data/incoming/`, not a fixture. Inspect, stage, ingest with `--dst-crs EPSG:3035`, run an analysis SQL that buffers or measures, then export to `data/outgoing/YYYY-MM-DD_qc-field-test/`. Record every command and its JSON.

- [ ] **Step 3: Exercise QC deliberately**

Four probes, each a real command:
1. `bin/qc` on the source file before ingest.
2. `bin/qc` on the analysis table with `--metric-op`, on a table in EPSG:4326, and confirm it warns.
3. An export driven by `--sql` with `--compare-to` the source table, and confirm the extent check reports `pass` rather than `not_evaluated`.
4. An export of a deliberately empty result with `--expect-non-empty`, and confirm the warning fires.

- [ ] **Step 4: Write the report**

Create `docs/reports/2026-09-XX_phase3-qc-field-test.md` with what ran, what QC said, what it missed, and anything awkward about the flags in practice. Note in particular whether `not_evaluated` was legible in real output or got lost in the noise, and whether raster `percent_nodata` under `-approx_stats` was accurate enough to trust.

- [ ] **Step 5: Commit**

```bash
git add docs/reports/
git commit -m "docs: Phase 3 QC field test report"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: scope and the Parquet section to Task 2 (`reader_sql` branch, `test_a_geoparquet_file_uses_the_read_parquet_branch`); the metrics shape to Tasks 2 and 3; the collector-agreement requirement to Task 2 Step 1 and `test_ogr_is_the_authority_on_dimensionality`; the result envelope and all five checks to Task 1; the ingest-versus-QC severity note to Task 4 Step 6 and Task 6 Step 3; `transform_bounds` to Task 1 (`reproject_bbox`, `test_bbox_comparison_crosses_crs`); the export reference order to Task 5 (`_export_reference`, all four tests); the approximate `percent_nodata` and `stats_mode` to Task 2's `file_raster_metrics`; the no-sidecar guarantee to Task 4's `test_raster_qc_reports_bands_without_writing_a_sidecar`; the warm-cache test caveat to the Global Constraints; documentation to Task 6; the field test to Task 7. No gaps.

**Placeholders.** None. Every code step carries the code; every run step carries the command and its expected output. The two conditional branches (Task 2 Step 1's three verifications, Task 2 Step 8's `ogrinfo` fallback) state the decision rule and both outcomes rather than deferring the decision.

**Type consistency.** `QcContext(expect_non_empty, metric_op, id_column, reference)` is constructed identically in Tasks 1, 4 and 5. `build_report(source, metrics, context)` and `qc_report(ref, context, *, exact_stats)` keep their signatures throughout. `file_metrics` and `table_metrics` both return `(source, metrics)`. `_stats_block` and `_dimension_stats`, defined in Task 2, are reused unchanged by Task 3. The envelope key is `qc_status` everywhere after Task 1 Step 4, including the Task 1 test correction in Step 5.
