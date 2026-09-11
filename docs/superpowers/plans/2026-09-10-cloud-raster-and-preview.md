# Cloud Raster and Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read an area of interest out of a cloud-hosted COG without downloading the
scene, and render any dataset to a deterministic PNG a vision model can check.

**Architecture:** A new `llm_gis/raster.py` shells out to the GDAL command line already
present in the image, windowing a remote COG through `/vsicurl` range requests into a
tiny VRT that pixels are never written for unless the caller asks. A new
`llm_gis/preview.py` frames a dataset and its AOI in EPSG:4326 and burns them into the
channels of a PNG. `planner.py` gains its raster row; `inspect.py` and `qc_collect.py`
learn remote URIs.

**Tech Stack:** Python 3.12, typer, pyproj, GDAL 3.13.3 command line (`gdalinfo`,
`gdal_translate`, `gdal_create`, `gdal_rasterize`, `ogr2ogr`, `gdal raster zonal-stats`),
pytest. No new dependency is added.

**Spec:** `docs/superpowers/specs/2026-09-10-cloud-raster-and-preview-design.md`

## Global Constraints

- **No new Python dependency.** Do not run `uv add`. `rasterio`, `matplotlib` and `PIL`
  are deliberately absent (spec, D8). Everything goes through `llm_gis.common.run_command`
  to a GDAL binary.
- **GDAL is pinned** to `ghcr.io/osgeo/gdal:ubuntu-small-3.13.3`. Do not change the
  Dockerfile.
- **Only `gdal raster zonal-stats` may use GDAL's provisional unified CLI** (spec, D9).
  Every other GDAL call uses a classic utility.
- **Never download a whole raster.** Remote reads go through `/vsicurl`; pixels are
  written only when the caller passes `--output`.
- **Run tests with `bin/test`**, which runs pytest inside the container, e.g.
  `bin/test tests/test_raster.py -v`. Live tests are excluded by default
  (`addopts = "-m 'not live'"` in `pyproject.toml`); run them with
  `bin/test tests/live/test_raster_remote.py -m live -v`.
- **Every command returns the existing envelope.** Success goes through `cli._emit`;
  failure raises `GisError` and is rendered by the `handle_errors` decorator.
- **No emojis in code. Docstrings explain why, not what.** Follow the surrounding style.
- Commit after every task. Do not push; do not open a PR unless asked.

## File Structure

| File | Responsibility |
|---|---|
| `llm_gis/common.py` (modify) | Gains `is_remote`, `gdal_uri`, and `reproject_bbox` moved down from `qc.py` |
| `llm_gis/inspect.py` (modify) | Accepts a remote URI; `Provenance(REMOTE_URI)` for one |
| `llm_gis/planner.py` (modify) | `GDAL` strategy, raster reader row, raster routing rules and steps |
| `llm_gis/raster.py` (create) | Windowed read, statistics, zonal statistics, COG export |
| `llm_gis/preview.py` (create) | Frame computation and PNG rendering only |
| `llm_gis/qc_collect.py` (modify) | Raster metrics from a remote URI and an optional window |
| `llm_gis/qc.py` (modify) | Imports `reproject_bbox` from `common` instead of defining it |
| `llm_gis/cli.py` (modify) | `raster-window` and `preview` commands; `inspect` takes `str` |
| `bin/raster-window`, `bin/preview` (create) | Thin docker wrappers, copied from `bin/inspect` |
| `tests/fixtures/make_fixtures.py` (modify) | Builds the committed COG fixture |
| `tests/test_gdal_uri.py`, `tests/test_raster.py`, `tests/test_preview.py` (create) | Offline unit tests |
| `tests/live/test_raster_remote.py` (create) | The `/vsicurl` Sentinel-2 path, marked `live` |

---

### Task 1: Remote URIs reach GDAL

Closes Phase 4's known limitation on its own: `bin/catalog-assets` finds Sentinel-2 COGs
and `bin/inspect` currently refuses their URLs.

**Files:**
- Modify: `llm_gis/common.py` (add two functions near `run_command`)
- Modify: `llm_gis/inspect.py:139-183` (`inspect_dataset`)
- Modify: `llm_gis/cli.py:76-83` (`inspect_cmd`)
- Create: `bin/` nothing; `bin/inspect` already forwards its arguments
- Test: `tests/test_gdal_uri.py` (create), `tests/test_inspect.py` (extend)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `common.is_remote(uri: str) -> bool`, `common.gdal_uri(uri: str) -> str` and
  `common.remote_read_error(uri: str, error: GisError) -> GisError`, used by every later
  task. `inspect.inspect_dataset(source: str, ingest_id: str | None = None) -> dict` —
  note the first parameter is now `str`, not `Path`. New error code
  `errors.REMOTE_READ_FAILED`.

- [ ] **Step 1: Write the failing test for the URI helpers**

Create `tests/test_gdal_uri.py`:

```python
"""The one place the VSI convention is stated. Pure; no GDAL runs here."""

from __future__ import annotations

from llm_gis.common import gdal_uri, is_remote


def test_an_https_url_becomes_a_vsicurl_path():
    assert gdal_uri("https://example.com/b.tif") == "/vsicurl/https://example.com/b.tif"


def test_an_http_url_becomes_a_vsicurl_path():
    assert gdal_uri("http://example.com/b.tif") == "/vsicurl/http://example.com/b.tif"


def test_an_s3_url_becomes_a_vsis3_path():
    """The scheme is dropped: /vsis3/ takes bucket/key, not the s3:// form."""
    assert gdal_uri("s3://bucket/key/b.tif") == "/vsis3/bucket/key/b.tif"


def test_a_local_path_passes_through_unchanged():
    assert gdal_uri("/data/incoming/elevation.tif") == "/data/incoming/elevation.tif"


def test_a_query_string_survives():
    """A signed URL carries its token after the path and GDAL needs all of it."""
    assert gdal_uri("https://e.com/b.tif?sig=x") == "/vsicurl/https://e.com/b.tif?sig=x"


def test_locality():
    assert is_remote("https://example.com/b.tif")
    assert is_remote("s3://bucket/b.tif")
    assert not is_remote("/data/incoming/b.tif")
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `bin/test tests/test_gdal_uri.py -v`
Expected: FAIL, `ImportError: cannot import name 'gdal_uri' from 'llm_gis.common'`

- [ ] **Step 3: Add the helpers to `llm_gis/common.py`**

Insert immediately above `def run_command(`:

```python
REMOTE_SCHEMES = ("http://", "https://", "s3://")


def is_remote(uri: str) -> bool:
    """Whether this source lives behind a network scheme rather than on disk.

    `planner.py` states the same tuple and deliberately does not import it: the
    planner stays free of this module's psycopg and pyproj imports so its whole
    test suite runs with no database.
    """
    return str(uri).startswith(REMOTE_SCHEMES)


def gdal_uri(uri: str) -> str:
    """A source as GDAL must be handed it: the VSI convention, stated once.

    Every GDAL invocation in this workspace goes through here, so a remote read
    is a range request rather than a download without any call site saying so.
    """
    text = str(uri)
    if text.startswith(("http://", "https://")):
        return f"/vsicurl/{text}"
    if text.startswith("s3://"):
        return f"/vsis3/{text[len('s3://'):]}"
    return text
```

- [ ] **Step 4: Run it to make sure it passes**

Run: `bin/test tests/test_gdal_uri.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Write the failing test for remote inspect**

Append to `tests/test_inspect.py`:

```python
def test_inspect_accepts_a_remote_uri_and_prefixes_vsicurl(monkeypatch):
    """No network here: we assert the argv GDAL would have been given."""
    seen = []

    def fake_run_command(args, **kwargs):
        seen.append(args)
        if args[0] == "ogrinfo":
            raise RuntimeError("not a vector")
        return json.dumps(
            {
                "size": [10980, 10980],
                "coordinateSystem": {"wkt": 'PROJCRS["WGS 84 / UTM zone 32N",ID["EPSG",32632]]'},
                "cornerCoordinates": {
                    "lowerLeft": [399960.0, 4990200.0],
                    "upperRight": [509760.0, 5100000.0],
                },
                "bands": [{"band": 1, "type": "UInt16", "noDataValue": 0.0}],
            }
        )

    monkeypatch.setattr("llm_gis.inspect.run_command", fake_run_command)

    report = inspect_dataset("https://example.com/scenes/B04.tif")

    assert report["dataset_kind"] == "raster"
    assert report["input_path"] == "https://example.com/scenes/B04.tif"
    assert seen[-1][-1] == "/vsicurl/https://example.com/scenes/B04.tif"


def test_inspect_missing_remote_uri_is_not_pre_checked(monkeypatch):
    """The .exists() guard is for local paths; a URL cannot be stat-ed."""

    def fake_run_command(args, **kwargs):
        raise RuntimeError("404")

    monkeypatch.setattr("llm_gis.inspect.run_command", fake_run_command)

    with pytest.raises(GisError) as error:
        inspect_dataset("https://example.com/missing.tif")
    assert error.value.code == UNSUPPORTED_FORMAT
```

Add `import json` and widen the existing import line to
`from llm_gis.errors import INPUT_NOT_FOUND, UNSUPPORTED_FORMAT, GisError`.

- [ ] **Step 6: Run it to make sure it fails**

Run: `bin/test tests/test_inspect.py -v`
Expected: FAIL — `inspect_dataset` builds a `Path` from the URL, which collapses
`https://` to `https:/`.

- [ ] **Step 7: Teach `inspect_dataset` about remote sources**

In `llm_gis/inspect.py`, widen the import from `common` to include `gdal_uri` and
`is_remote`, and replace the head of `inspect_dataset`:

```python
def inspect_dataset(source: str | Path, ingest_id: str | None = None) -> dict[str, Any]:
    """Measure a dataset. `source` is a local path or a remote http/https/s3 URI."""
    ensure_workspace_dirs()
    source = str(source)
    if not is_remote(source) and not Path(source).exists():
        raise GisError(
            INPUT_NOT_FOUND,
            f"Input path does not exist: {source}",
            "Check the path and try again",
        )
    target = gdal_uri(source)

    vector_out: dict[str, Any] | None = None
    raster_out: dict[str, Any] | None = None

    try:
        vector_out = json.loads(run_command(["ogrinfo", "-json", "-ro", target]))
    except Exception:
        vector_out = None

    try:
        raster_out = json.loads(run_command(["gdalinfo", "-json", target]))
    except Exception:
        raster_out = None

    if not vector_out and not raster_out:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"Neither ogrinfo nor gdalinfo could read {source}",
            "Confirm the file is a GDAL-readable vector or raster; for a sidecar format ensure companion files are present",
        )
```

Then change the two builder calls to pass `source` rather than `input_path`, and in
both `_build_vector_asset` and `_build_raster_asset` change the signature's first
parameter to `source: str`, `uri=source`, and the provenance to:

```python
    provenance=Provenance(
        REMOTE_URI if is_remote(source) else LOCAL_FILE, retrieved_at=utc_now()
    ),
```

Import `REMOTE_URI` from `llm_gis.asset` alongside `LOCAL_FILE`.

- [ ] **Step 8: Widen the CLI argument from `Path` to `str`**

In `llm_gis/cli.py`, `inspect_cmd`:

```python
@app.command("inspect")
@handle_errors
def inspect_cmd(
    source: str = typer.Argument(..., help="Path or http/https/s3 URI to a vector or raster"),
    ingest_id: str | None = typer.Option(None, help="Optional report id"),
) -> None:
    _emit("inspect", inspect_dataset(source, ingest_id=ingest_id))
```

This change is required, not cosmetic: `typer` would otherwise construct a `Path` and
`Path("https://e.com/b.tif")` silently becomes `https:/e.com/b.tif`.

- [ ] **Step 9: Write the failing test for a failed remote read**

The spec asks that a remote failure name itself, so a 403 on a requester-pays bucket does
not read as a malformed file. Append to `tests/test_gdal_uri.py`:

```python
import pytest

from llm_gis.common import GisError, remote_read_error


def test_a_remote_failure_names_itself_and_carries_the_status():
    inner = GisError(
        "COMMAND_FAILED",
        "Command failed with exit 1: gdalinfo -json /vsicurl/https://e.com/b.tif",
        "Read details.stderr for the underlying tool diagnostic",
        {"stderr": "ERROR 11: HTTP response code: 403"},
    )

    with pytest.raises(GisError) as error:
        raise remote_read_error("https://e.com/b.tif", inner)

    assert error.value.code == "REMOTE_READ_FAILED"
    assert error.value.details["http_status"] == 403
    assert error.value.details["uri"] == "https://e.com/b.tif"


def test_a_remote_failure_with_no_status_still_reports_the_uri():
    inner = GisError("COMMAND_FAILED", "boom", "look at stderr", {"stderr": "ERROR 4: no such file"})

    raised = remote_read_error("https://e.com/b.tif", inner)

    assert raised.details["http_status"] is None
```

Add `from llm_gis.errors import GisError` to the imports if `common` does not re-export it.

- [ ] **Step 10: Run it to make sure it fails**

Run: `bin/test tests/test_gdal_uri.py -v`
Expected: FAIL, `ImportError: cannot import name 'remote_read_error'`.

- [ ] **Step 11: Add the error code and the mapper**

In `llm_gis/errors.py`, beside the existing codes:

```python
REMOTE_READ_FAILED = "REMOTE_READ_FAILED"
```

In `llm_gis/common.py`, below `gdal_uri`:

```python
def remote_read_error(uri: str, error: GisError) -> GisError:
    """A failed range request, named as one.

    GDAL reports an HTTP failure as a generic non-zero exit, which reads like a
    malformed file. Pulling the status out means a 403 on a requester-pays bucket
    suggests credentials rather than a corrupt raster.
    """
    stderr = str(error.details.get("stderr", ""))
    match = re.search(r"HTTP response code:\s*(\d{3})", stderr)
    status = int(match.group(1)) if match else None
    return GisError(
        REMOTE_READ_FAILED,
        f"Could not read {uri} over HTTP",
        "Check the URI, and whether the bucket needs credentials or is requester-pays",
        {"uri": uri, "http_status": status, "stderr": stderr[-500:]},
    )
```

Import `REMOTE_READ_FAILED` from `llm_gis.errors` at the top of `common.py`.

- [ ] **Step 12: Use it where remote reads happen**

In `llm_gis/inspect.py`, the `gdalinfo` attempt currently swallows every exception so the
vector and raster probes can both be tried. Keep that, but remember the failure and raise
a named error when neither probe worked and the source is remote:

```python
    remote_failure: GisError | None = None
    try:
        raster_out = json.loads(run_command(["gdalinfo", "-json", target]))
    except GisError as error:
        remote_failure = error
        raster_out = None
    except Exception:
        raster_out = None

    if not vector_out and not raster_out:
        if is_remote(source) and remote_failure is not None:
            raise remote_read_error(source, remote_failure)
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"Neither ogrinfo nor gdalinfo could read {source}",
            "Confirm the file is a GDAL-readable vector or raster; for a sidecar format ensure companion files are present",
        )
```

The earlier `test_inspect_missing_remote_uri_is_not_pre_checked` raises a bare
`RuntimeError`, not a `GisError`, so it keeps expecting `UNSUPPORTED_FORMAT` and still
passes. That is the intended split: a tool that failed for a reason we can name gets the
named error, anything else falls through to the honest generic one.

- [ ] **Step 13: Run the whole suite**

Run: `bin/test tests/ -v`
Expected: PASS, including the pre-existing `test_inspect_missing_path_raises`.

- [ ] **Step 14: Commit**

```bash
git add llm_gis/common.py llm_gis/errors.py llm_gis/inspect.py llm_gis/cli.py \
        tests/test_gdal_uri.py tests/test_inspect.py
git commit -m "feat: inspect reads remote URIs through /vsicurl"
```

---

### Task 2: The planner's raster row

**Files:**
- Modify: `llm_gis/planner.py` (constants, `READERS`, `route`, `_query_route`,
  `_analyse_route`, `_export_route`, `steps`)
- Test: `tests/test_planner.py` (extend), `tests/test_plan_cli.py` (extend)

**Interfaces:**
- Consumes: nothing. `planner.py` imports only `llm_gis.errors` and stays that way.
- Produces: `planner.GDAL = "gdal"`; `classify(<any .tif>).readers == ["gdal", "postgis"]`;
  a `raster-window` step in `steps()`. `catalog.readers_for` picks this up with no edit.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_planner.py`:

```python
from llm_gis.planner import GDAL, RASTER, REMOTE_RANGE_READ


def test_a_cog_is_readable_by_gdal_and_postgis():
    """Two live routes, not one dressed up: read the window, or ingest the raster."""
    source = classify("https://e.com/scenes/B04.tif")
    assert source.format == RASTER
    assert source.readers == [GDAL, POSTGIS]


def test_a_raster_query_without_materialise_reads_the_window_in_place():
    decided = route("query", classify("https://e.com/B04.tif"))
    assert decided.strategy == GDAL
    assert decided.fallback["strategy"] == POSTGIS


def test_a_raster_query_with_materialise_goes_to_the_workspace():
    decided = route("query", classify("/data/incoming/elevation.tif"), materialise=True)
    assert decided.strategy == POSTGIS
    assert "survive" in decided.reason


def test_a_remote_cog_read_is_flagged_efficient_not_unindexed():
    """The opposite of REMOTE_UNINDEXED_READ: this is the case ranges were made for."""
    decided = route("query", classify("https://e.com/B04.tif"))
    codes = [w["code"] for w in decided.warnings]
    assert REMOTE_RANGE_READ in codes
    assert "REMOTE_UNINDEXED_READ" not in codes


def test_a_local_raster_read_carries_no_range_warning():
    decided = route("query", classify("/data/incoming/elevation.tif"))
    assert decided.warnings == []


def test_analyse_on_a_raster_is_blocked_and_names_zones():
    decided = route("analyse", classify("https://e.com/B04.tif"))
    assert decided.strategy is None
    assert "--zones" in decided.blocked_by["suggested_action"]


def test_a_raster_query_plans_a_raster_window_step():
    source = classify("https://e.com/B04.tif")
    decided = route("query", source)
    plan = steps("query", source, decided, bbox="8.9,45.9,9.0,46.0", output="/data/outgoing/aoi.tif")
    assert [s.command for s in plan] == ["raster-window"]
    assert "--bbox" in plan[0].argv
    assert "--output" in plan[0].argv


def test_a_materialised_raster_plans_stage_then_ingest_raster():
    source = classify("/data/incoming/elevation.tif")
    decided = route("query", source, materialise=True)
    plan = steps("query", source, decided)
    assert [s.command for s in plan] == ["stage", "ingest-raster"]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `bin/test tests/test_planner.py -v`
Expected: FAIL, `ImportError: cannot import name 'GDAL'`.

- [ ] **Step 3: Add the strategy, the reader row and the warning code**

In `llm_gis/planner.py`:

```python
DUCKDB = "duckdb"
POSTGIS = "postgis"
GDAL = "gdal"
```

```python
READERS = {
    PARQUET: [DUCKDB],
    VECTOR_FILE: [DUCKDB, POSTGIS],
    POSTGIS_TABLE: [POSTGIS],
    RASTER: [GDAL, POSTGIS],
}
```

```python
REMOTE_RANGE_READ = "REMOTE_RANGE_READ"

BLOCKED_RASTER_ANALYSE = {
    "code": NO_CONVERSION_PATH,
    "message": (
        "SQL across sources runs in the workspace, and pixel statistics over a tiled "
        "PostGIS raster table are not implemented here."
    ),
    "suggested_action": (
        "Use bin/raster-window --zones <vector> for statistics by area, which needs no "
        "database and reads only the window."
    ),
}
```

Generalise `_blocked` so it can carry either payload:

```python
def _blocked(reason: str, payload: dict | None = None) -> Route:
    return Route(strategy=None, reason=reason, blocked_by=dict(payload or BLOCKED_PARQUET))
```

- [ ] **Step 4: Add the routing rules**

In `_query_route`, immediately after the `POSTGIS_TABLE` branch:

```python
    if source.format == RASTER:
        if materialise:
            return Route(
                POSTGIS,
                "the pixels must survive this command, and the workspace is where results live",
                fallback={"strategy": GDAL, "requires": None, "loses": "persistence"},
            )
        warnings = []
        if source.locality == REMOTE:
            warnings.append(
                {
                    "code": REMOTE_RANGE_READ,
                    "message": (
                        "A remote COG is read by range request: only the window's bytes "
                        "cross the network, not the scene"
                    ),
                    "severity": "info",
                }
            )
        return Route(
            GDAL,
            "a COG is read in place through range requests, and no persistence was requested",
            fallback={"strategy": POSTGIS, "requires": "stage and ingest-raster first", "loses": None},
            warnings=warnings,
        )
```

In `_analyse_route`, before the final return:

```python
    if source.format == RASTER:
        return _blocked(
            "pixel statistics belong to the raster reader, not to workspace SQL",
            BLOCKED_RASTER_ANALYSE,
        )
```

In `_export_route`, before the final return:

```python
    if source.format == RASTER:
        return Route(GDAL, "the source never enters the database")
```

- [ ] **Step 5: Delete the deferral and add the steps**

In `route`, the `if not source.readers:` guard can no longer fire for raster. Leave the
guard (a future format may need it) but change its `suggested_action` to
`"Give a Parquet, GeoParquet, vector file, raster, or a schema.table name"` so no message
in the module still promises a phase that has arrived.

In `steps`, immediately after the `if decided.strategy is None: return []` guard:

```python
    if decided.strategy == GDAL:
        return [
            Step(
                "raster-window",
                [source.uri, *_flags(bbox=bbox, output=output)],
                "read the AOI out of the raster without downloading the scene",
            )
        ]

    if source.format == RASTER:
        ingest_id = _ingest_id(source.uri)
        name = Path(source.uri.split("?")[0]).name
        return [
            Step("stage", [source.uri, "--ingest-id", ingest_id],
                 "copy the source into the workspace and hash it"),
            Step("ingest-raster",
                 [f"/data/work/staging/{ingest_id}/{name}", "--table", ingest_id,
                  "--ingest-id", ingest_id],
                 "load the raster into PostGIS, where later steps can reach it"),
        ]
```

- [ ] **Step 6: Run the tests**

Run: `bin/test tests/test_planner.py tests/test_plan_cli.py -v`
Expected: PASS.

- [ ] **Step 7: Confirm the free dividend in catalog**

Add to `tests/test_catalog_operations.py`:

```python
def test_a_discovered_cog_now_reports_a_reader():
    """catalog.readers_for delegates to the planner, so Phase 7 fixes this with no edit here."""
    from llm_gis.catalog import readers_for

    assert readers_for("https://e.com/scenes/B04.tif") == ["gdal", "postgis"]
    assert readers_for(None) == []
```

Run: `bin/test tests/test_catalog_operations.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add llm_gis/planner.py tests/test_planner.py tests/test_catalog_operations.py
git commit -m "feat: the planner routes raster, and discovered COGs report a reader"
```

---

### Task 3: The windowed read

The heart of the phase. A VRT describes the window without holding a pixel: measured at
1765 bytes for a Sentinel-2 AOI, with `gdalinfo -stats` over it taking 5.1s and reading
only that window.

**Files:**
- Create: `llm_gis/raster.py`
- Modify: `llm_gis/common.py` (move `reproject_bbox` in from `qc.py`)
- Modify: `llm_gis/qc.py:36-46` (import it instead of defining it)
- Modify: `llm_gis/cli.py` (add `raster-window`)
- Create: `bin/raster-window`
- Modify: `tests/fixtures/make_fixtures.py`
- Test: `tests/test_raster.py`

**Interfaces:**
- Consumes: `common.gdal_uri`, `common.is_remote` (Task 1).
- Produces:
  - `common.reproject_bbox(bbox: dict | None, src_crs: str | None, dst_crs: str | None) -> dict | None`
  - `raster.window(source: str, *, bbox: tuple[float, float, float, float], bbox_crs: str = "EPSG:4326", band: int = 1, t_srs: str | None = None, stats: bool = True, output: str | None = None, zones: str | None = None, zone_stats: list[str] | None = None, ingest_id: str | None = None) -> dict`
  - `raster.window_vrt(source: str, bbox, bbox_crs, t_srs, work_dir: Path) -> Path`
  - `raster.band_stats(target: str) -> list[dict]`
  - Result keys: `source`, `bbox`, `bbox_native`, `bbox_4326`, `crs`, `size`,
    `aoi_intersects`, `bands`, `zonal`, `output`, `created_at`.
  Task 4 adds `zones`/`zone_stats` behaviour; the parameters are declared here so the
  signature does not change under a later task.

- [ ] **Step 1: Add the COG fixture generator**

Append to `tests/fixtures/make_fixtures.py`, and add a call to it in `main()` beside the
existing calls:

```python
def make_scene_cog() -> None:
    """A small COG in UTM 32N, so windowing is exercised across a CRS boundary.

    Deliberately not EPSG:4326: a bbox given in degrees against a metre-based raster is
    the mistake bin/preview exists to catch, and the tests need a raster that can make it.
    """
    plain = FIXTURES_DIR / "_scene_plain.tif"
    subprocess.run(
        ["gdal_create", "-outsize", "512", "512", "-bands", "1", "-ot", "UInt16",
         "-a_srs", "EPSG:32632", "-a_ullr", "399960", "5100000", "405080", "5094880",
         "-burn", "1200", str(plain)],
        check=True,
    )
    subprocess.run(
        ["gdal_translate", "-q", "-of", "COG", "-co", "COMPRESS=DEFLATE",
         str(plain), str(FIXTURES_DIR / "scene.tif")],
        check=True,
    )
    plain.unlink()
```

Run: `bin/test --collect-only -q` is not the check here. Instead run
`docker compose run --rm agent uv run python tests/fixtures/make_fixtures.py`
Expected: `tests/fixtures/scene.tif` exists. Confirm with
`docker compose run --rm agent gdalinfo -json tests/fixtures/scene.tif | grep LAYOUT`
Expected: `"LAYOUT":"COG"`.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_raster.py`:

```python
"""The windowed read, against a committed COG. No network in this file."""

from __future__ import annotations

from pathlib import Path

import pytest

from llm_gis import raster
from llm_gis.errors import GisError

FIXTURES = Path(__file__).parent / "fixtures"
SCENE = str(FIXTURES / "scene.tif")

# The fixture spans 399960..405080 E, 5094880..5100000 N in EPSG:32632,
# which is roughly 8.897..8.963 E, 45.977..46.024 N in EPSG:4326.
INSIDE = (8.91, 45.99, 8.94, 46.01)
OUTSIDE = (2.0, 48.0, 2.1, 48.1)


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))


def test_a_window_reports_both_bboxes_and_the_native_crs():
    result = raster.window(SCENE, bbox=INSIDE)

    assert "32632" in result["crs"]
    assert result["aoi_intersects"] is True
    assert result["bbox_native"]["minx"] > 399000
    assert 8.9 < result["bbox_4326"]["minx"] < 9.0


def test_a_window_measures_the_band_it_was_asked_for():
    result = raster.window(SCENE, bbox=INSIDE)

    band = result["bands"][0]
    assert band["index"] == 1
    assert band["min"] == 1200.0
    assert band["max"] == 1200.0


def test_no_output_writes_no_pixels(tmp_path):
    result = raster.window(SCENE, bbox=INSIDE)

    assert result["output"] is None
    assert not list(tmp_path.rglob("*.tif"))


def test_output_writes_a_cog():
    import json
    from llm_gis.common import run_command, work_root as root

    destination = root() / "outgoing_test.tif"
    result = raster.window(SCENE, bbox=INSIDE, output=str(destination))

    assert result["output"] == str(destination)
    info = json.loads(run_command(["gdalinfo", "-json", str(destination)]))
    assert info["metadata"]["IMAGE_STRUCTURE"]["LAYOUT"] == "COG"


def test_a_reprojected_window_carries_the_requested_crs():
    result = raster.window(SCENE, bbox=INSIDE, t_srs="EPSG:3857")
    assert "3857" in result["crs"]


def test_an_aoi_outside_the_raster_is_a_finding_not_an_error():
    result = raster.window(SCENE, bbox=OUTSIDE)

    assert result["aoi_intersects"] is False
    assert result["bands"] == []
    assert result["output"] is None


def test_a_bbox_in_the_wrong_order_is_refused():
    with pytest.raises(GisError) as error:
        raster.window(SCENE, bbox=(9.0, 46.0, 8.9, 45.9))
    assert error.value.code == "MISSING_ARGUMENT"
```

- [ ] **Step 3: Run them to make sure they fail**

Run: `bin/test tests/test_raster.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'llm_gis.raster'`.

- [ ] **Step 4: Move `reproject_bbox` into `common.py`**

Cut the function body from `llm_gis/qc.py` and paste it into `llm_gis/common.py` below
`normalize_crs`, unchanged apart from its docstring gaining a sentence:

```python
def reproject_bbox(
    bbox: dict[str, float] | None, src_crs: str | None, dst_crs: str | None
) -> dict[str, float] | None:
    """Transform a bbox, densifying the edges so a curved edge is not clipped off.

    Shared by QC's disjointness check and by the raster reader, which reports every
    window in its native CRS and in 4326 so a caller can compare the two.
    """
    if bbox is None or not src_crs or not dst_crs or src_crs == dst_crs:
        return bbox
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    minx, miny, maxx, maxy = transformer.transform_bounds(
        bbox["minx"], bbox["miny"], bbox["maxx"], bbox["maxy"]
    )
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}
```

Add `from pyproj import CRS, Transformer` to `common.py`'s imports. In `qc.py`, delete
the definition and add `reproject_bbox` to the existing
`from llm_gis.common import ...` line — the name stays importable from `llm_gis.qc`, so
`tests/test_qc_checks.py` is unaffected.

Run: `bin/test tests/test_qc_checks.py -v`
Expected: PASS, unchanged.

- [ ] **Step 5: Write `llm_gis/raster.py`**

```python
"""Read an area of interest out of a raster without downloading it.

A window is a VRT: a description of which pixels are wanted, measured at under two
kilobytes for a Sentinel-2 AOI. Statistics and zonal statistics run against that VRT,
so a remote scene crosses the network as range requests over the window alone.
Pixels are written only when the caller names an --output, which is the whole of
"materialise only when required" for raster.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_gis.common import (
    ensure_workspace_dirs,
    gdal_uri,
    normalize_crs,
    reproject_bbox,
    run_command,
    utc_now,
    work_root,
    write_json,
)
from llm_gis.errors import MISSING_ARGUMENT, GisError

WGS84 = "EPSG:4326"


def _as_bbox(values: tuple[float, float, float, float]) -> dict[str, float]:
    minx, miny, maxx, maxy = (float(v) for v in values)
    if minx >= maxx or miny >= maxy:
        raise GisError(
            MISSING_ARGUMENT,
            f"Bounding box is empty or inverted: {values}",
            "Give it as minx,miny,maxx,maxy in the CRS named by --bbox-crs",
            {"bbox": list(values)},
        )
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def _info(target: str, *, stats: bool = False) -> dict[str, Any]:
    """gdalinfo as JSON. PAM is disabled: a .aux.xml beside a read-only source fails."""
    import os

    args = ["gdalinfo", "-json"]
    if stats:
        args.append("-stats")
    env = {**os.environ, "GDAL_PAM_ENABLED": "NO"}
    return json.loads(run_command([*args, target], env=env))


def _extent(payload: dict[str, Any]) -> dict[str, float] | None:
    corners = payload.get("cornerCoordinates") or {}
    xs = [float(c[0]) for c in corners.values() if c]
    ys = [float(c[1]) for c in corners.values() if c]
    if not xs:
        return None
    return {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}


def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["maxx"] < b["minx"] or b["maxx"] < a["minx"]
        or a["maxy"] < b["miny"] or b["maxy"] < a["miny"]
    )


def window_vrt(
    source: str,
    bbox: dict[str, float],
    bbox_crs: str,
    t_srs: str | None,
    work_dir: Path,
) -> Path:
    """Describe the window as a VRT. No pixels are read or written by this call.

    -projwin_srs lets GDAL do the corner transform itself, so the AOI is never
    silently interpreted in the raster's own units.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    destination = work_dir / "window.vrt"
    args = [
        "gdal_translate", "-q", "-of", "VRT",
        "-projwin_srs", bbox_crs,
        "-projwin", str(bbox["minx"]), str(bbox["maxy"]), str(bbox["maxx"]), str(bbox["miny"]),
    ]
    if t_srs:
        args = ["gdalwarp", "-q", "-of", "VRT", "-t_srs", t_srs,
                "-te_srs", bbox_crs,
                "-te", str(bbox["minx"]), str(bbox["miny"]), str(bbox["maxx"]), str(bbox["maxy"])]
    run_command([*args, gdal_uri(source), str(destination)])
    return destination


def band_stats(target: str) -> list[dict[str, Any]]:
    """Exact statistics over whatever the target covers, which is the window."""
    payload = _info(target, stats=True)
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
                "stdev": band.get("stdDev"),
                "percent_nodata": None if valid_percent is None else 100.0 - float(valid_percent),
            }
        )
    return bands


def window(
    source: str,
    *,
    bbox: tuple[float, float, float, float],
    bbox_crs: str = WGS84,
    band: int = 1,
    t_srs: str | None = None,
    stats: bool = True,
    output: str | None = None,
    zones: str | None = None,
    zone_stats: list[str] | None = None,
    ingest_id: str | None = None,
) -> dict[str, Any]:
    """Read one AOI out of a raster. Writes pixels only when `output` is given."""
    ensure_workspace_dirs()
    aoi = _as_bbox(bbox)

    scene = _info(gdal_uri(source))
    scene_crs = normalize_crs((scene.get("coordinateSystem") or {}).get("wkt"))
    scene_bbox = _extent(scene)
    aoi_in_scene = reproject_bbox(aoi, bbox_crs, scene_crs)

    result: dict[str, Any] = {
        "source": source,
        "bbox": aoi,
        "bbox_crs": bbox_crs,
        "crs": scene_crs,
        "size": None,
        "bbox_native": None,
        "bbox_4326": None,
        "aoi_intersects": bool(scene_bbox and aoi_in_scene and _intersects(scene_bbox, aoi_in_scene)),
        "bands": [],
        "zonal": None,
        "output": None,
        "created_at": utc_now(),
    }
    if not result["aoi_intersects"]:
        return _record(result, ingest_id)

    work_dir = work_root() / "raster" / (ingest_id or "window")
    vrt = window_vrt(source, aoi, bbox_crs, t_srs, work_dir)
    measured = _info(str(vrt))
    window_crs = normalize_crs((measured.get("coordinateSystem") or {}).get("wkt"))
    native = _extent(measured)

    result["crs"] = window_crs
    result["size"] = measured.get("size")
    result["bbox_native"] = native
    result["bbox_4326"] = reproject_bbox(native, window_crs, WGS84)
    if stats:
        result["bands"] = band_stats(str(vrt))
    if output:
        run_command([
            "gdal_translate", "-q", "-of", "COG", "-co", "COMPRESS=DEFLATE",
            "-b", str(band), str(vrt), output,
        ])
        result["output"] = output
    return _record(result, ingest_id)


def _record(result: dict[str, Any], ingest_id: str | None) -> dict[str, Any]:
    """Provenance for a produced asset, following the analysis.json convention."""
    if ingest_id:
        write_json(work_root() / "reports" / f"{ingest_id}.raster.json", result)
    return result
```

- [ ] **Step 6: Run the tests**

Run: `bin/test tests/test_raster.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 7: Add the CLI command**

In `llm_gis/cli.py`, import `from llm_gis.raster import window as raster_window` and add:

```python
@app.command("raster-window")
@handle_errors
def raster_window_cmd(
    source: str = typer.Argument(..., help="Path or http/https/s3 URI to a raster"),
    bbox: str = typer.Option(..., "--bbox", help="minx,miny,maxx,maxy"),
    bbox_crs: str = typer.Option("EPSG:4326", "--bbox-crs", help="CRS the bbox is given in"),
    band: int = typer.Option(1, "--band", help="Band to export, 1-based"),
    t_srs: str | None = typer.Option(None, "--t-srs", help="Reproject the window to this CRS"),
    stats: bool = typer.Option(True, "--stats/--no-stats", help="Exact statistics over the window"),
    output: str | None = typer.Option(None, "--output", help="Write a COG here; omit to write nothing"),
    ingest_id: str | None = typer.Option(None, help="Optional report id"),
) -> None:
    values = _parse_bbox(bbox)
    _emit(
        "raster-window",
        raster_window(
            source, bbox=tuple(values), bbox_crs=bbox_crs, band=band,
            t_srs=t_srs, stats=stats, output=output, ingest_id=ingest_id,
        ),
    )
```

`_parse_bbox` already exists at `cli.py:236` and returns four floats, raising
`typer.BadParameter` on anything else — which is what this command needs. Change only its
docstring, which currently reads "always lon/lat WGS84 for STAC" and is no longer true now
that `--bbox-crs` exists:

```python
def _parse_bbox(bbox: str | None) -> list[float] | None:
    """Four comma-separated numbers as minx,miny,maxx,maxy.

    STAC search always means lon/lat WGS84; raster-window means whatever --bbox-crs says.
    """
```

- [ ] **Step 8: Add the wrapper script**

```bash
sed 's/llm-gis inspect/llm-gis raster-window/' bin/inspect > bin/raster-window
chmod +x bin/raster-window
```

Verify: `bin/raster-window tests/fixtures/scene.tif --bbox 8.91,45.99,8.94,46.01`
Expected: a JSON envelope with `"status": "ok"`, `"aoi_intersects": true`, one band with
min and max 1200.

- [ ] **Step 9: Commit**

```bash
git add llm_gis/raster.py llm_gis/common.py llm_gis/qc.py llm_gis/cli.py bin/raster-window \
        tests/test_raster.py tests/fixtures/make_fixtures.py tests/fixtures/scene.tif
git commit -m "feat: bin/raster-window reads an AOI without downloading the scene"
```

---

### Task 4: Zonal statistics, with our own CRS check

GDAL warned "Inputs and zones do not have the same SRS" and computed anyway against a
GeoJSON whose coordinates were UTM. The values happened to be right. This task makes the
check ours.

**Files:**
- Modify: `llm_gis/raster.py` (add `zonal_stats`, wire the `zones` parameter)
- Modify: `llm_gis/cli.py` (`--zones`, `--zone-stat`)
- Test: `tests/test_raster.py` (extend)

**Interfaces:**
- Consumes: `raster.window_vrt`, `raster.window` (Task 3).
- Produces: `raster.zonal_stats(target: str, zones: str, stats: list[str], work_dir: Path, raster_crs: str | None) -> list[dict]`. `window()`'s
  result gains a populated `zonal` list of dicts, one per zone feature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_raster.py`:

```python
DEFAULT_STATS = ["count", "mean", "min", "max", "stdev"]


def _zones_4326(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box

    path = tmp_path / "zones.gpkg"
    gpd.GeoDataFrame(
        {"name": ["left", "right"]},
        geometry=[box(8.91, 45.99, 8.92, 46.00), box(8.93, 45.99, 8.94, 46.00)],
        crs="EPSG:4326",
    ).to_file(path, driver="GPKG")
    return str(path)


def test_zonal_statistics_return_one_row_per_zone(tmp_path):
    result = raster.window(SCENE, bbox=INSIDE, zones=_zones_4326(tmp_path))

    assert len(result["zonal"]) == 2
    assert {row["name"] for row in result["zonal"]} == {"left", "right"}
    assert result["zonal"][0]["mean"] == 1200.0
    assert result["zonal"][0]["count"] > 0


def test_zones_in_a_different_crs_are_reprojected_not_assumed(tmp_path, monkeypatch):
    """The zones arrive in 4326 against a 32632 raster; we reproject before GDAL sees them."""
    seen = []
    real = raster.run_command

    def spy(args, **kwargs):
        seen.append(args)
        return real(args, **kwargs)

    monkeypatch.setattr(raster, "run_command", spy)
    raster.window(SCENE, bbox=INSIDE, zones=_zones_4326(tmp_path))

    reprojections = [a for a in seen if a[0] == "ogr2ogr" and "-t_srs" in a]
    assert reprojections, "zones must be reprojected explicitly, not left to GDAL's warning"


def test_zone_statistics_are_selectable(tmp_path):
    result = raster.window(SCENE, bbox=INSIDE, zones=_zones_4326(tmp_path), zone_stats=["count"])

    assert "count" in result["zonal"][0]
    assert "stdev" not in result["zonal"][0]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `bin/test tests/test_raster.py -k zon -v`
Expected: FAIL — `result["zonal"]` is `None`.

- [ ] **Step 3: Implement `zonal_stats`**

Add to `llm_gis/raster.py`:

```python
DEFAULT_ZONE_STATS = ["count", "mean", "min", "max", "stdev"]


def _vector_crs(path: str) -> str | None:
    payload = json.loads(run_command(["ogrinfo", "-json", "-ro", gdal_uri(path)]))
    layer = (payload.get("layers") or [{}])[0]
    field = (layer.get("geometryFields") or [{}])[0]
    from llm_gis.common import crs_text_from_ogr_coordinate_system

    return normalize_crs(crs_text_from_ogr_coordinate_system(field.get("coordinateSystem") or {}))


def zonal_stats(
    target: str,
    zones: str,
    stats: list[str],
    work_dir: Path,
    raster_crs: str | None,
) -> list[dict[str, Any]]:
    """Statistics per zone, with the zone CRS reconciled here rather than by GDAL.

    `gdal raster zonal-stats` warns on an SRS mismatch and computes anyway, which is a
    silently wrong answer waiting to happen. We reproject first, so the warning cannot fire.
    """
    zone_crs = _vector_crs(zones)
    prepared = zones
    if raster_crs and zone_crs and zone_crs != raster_crs:
        prepared = str(work_dir / "zones.gpkg")
        run_command([
            "ogr2ogr", "-q", "-t_srs", raster_crs, "-f", "GPKG", prepared, gdal_uri(zones),
        ])

    destination = work_dir / "zonal.geojson"
    args = ["gdal", "raster", "zonal-stats", "-q", "--overwrite",
            "-i", target, "--zones", prepared, "-f", "GeoJSON", "-o", str(destination)]
    for name in stats:
        args += ["--stat", name]
    run_command(args)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    return [feature.get("properties", {}) for feature in payload.get("features", [])]
```

Note for the implementer: this is the one call in the phase that uses GDAL's provisional
unified CLI (spec, D9). Do not reach for it anywhere else.

- [ ] **Step 4: Wire it into `window`**

In `window`, after the `if stats:` block:

```python
    if zones:
        result["zonal"] = zonal_stats(
            str(vrt), zones, zone_stats or DEFAULT_ZONE_STATS, work_dir, window_crs
        )
```

`--include-field` is deliberately not passed: `gdal raster zonal-stats` carries the zone
attributes through by default when no field list is given, and naming fields would mean
guessing at the caller's schema.

- [ ] **Step 5: Run the tests**

Run: `bin/test tests/test_raster.py -v`
Expected: PASS, 10 tests.

If the zone attributes do not appear in the output properties, add
`args += ["--include-field", name]` for each attribute reported by
`ogrinfo -json` on the prepared zones, and re-run.

- [ ] **Step 6: Add the CLI flags**

Extend `raster_window_cmd` in `llm_gis/cli.py`:

```python
    zones: str | None = typer.Option(None, "--zones", help="Vector dataset of zones for statistics by area"),
    zone_stat: list[str] = typer.Option([], "--zone-stat", help="Statistic per zone; repeatable"),
```

and pass `zones=zones, zone_stats=list(zone_stat) or None` through to `raster_window`.

- [ ] **Step 7: Commit**

```bash
git add llm_gis/raster.py llm_gis/cli.py tests/test_raster.py
git commit -m "feat: zonal statistics over a window, with the zone CRS reconciled first"
```

---

### Task 5: QC over a remote or windowed raster

Closes the item Phase 3 deferred: remote URIs as a QC source.

**Files:**
- Modify: `llm_gis/qc_collect.py:189-235` (`file_raster_metrics`, `file_metrics`)
- Modify: `llm_gis/qc.py:137-152` (`resolve_source`, `qc_report`)
- Modify: `llm_gis/cli.py` (`qc` gains `--bbox`)
- Test: `tests/test_qc_file.py` (extend)

**Interfaces:**
- Consumes: `common.gdal_uri`, `common.is_remote` (Task 1); `raster.window_vrt` (Task 3).
- Produces: `qc_collect.file_raster_metrics(source: str, exact_stats: bool, bbox: dict | None = None, bbox_crs: str = "EPSG:4326") -> dict` — the first parameter widens from `Path` to `str`, and `file_metrics` gains the same two trailing parameters. The returned
  shape is unchanged, so every existing check keeps working.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_qc_file.py`:

```python
def test_qc_reads_a_raster_through_the_gdal_uri_helper(monkeypatch):
    """A remote raster is a QC source now; assert the argv rather than hit the network."""
    import json as json_module

    seen = []

    def fake_run_command(args, **kwargs):
        seen.append(args)
        return json_module.dumps(
            {
                "size": [10, 10],
                "geoTransform": [0, 10.0, 0, 10, 0, -10.0],
                "coordinateSystem": {"wkt": 'PROJCRS["x",ID["EPSG",32632]]'},
                "cornerCoordinates": {"lowerLeft": [0, 0], "upperRight": [100, 100]},
                "bands": [{"band": 1, "minimum": 1.0, "maximum": 2.0, "noDataValue": None}],
            }
        )

    monkeypatch.setattr("llm_gis.qc_collect.run_command", fake_run_command)

    metrics = qc_collect.file_raster_metrics("https://e.com/B04.tif", False)

    assert metrics["raster"]["width"] == 10
    assert seen[0][-1] == "/vsicurl/https://e.com/B04.tif"


def test_qc_over_a_window_measures_the_window_not_the_scene():
    scene = str(Path(__file__).parent / "fixtures" / "scene.tif")
    whole = qc_collect.file_raster_metrics(scene, True)
    windowed = qc_collect.file_raster_metrics(
        scene, True, bbox={"minx": 8.91, "miny": 45.99, "maxx": 8.92, "maxy": 46.00}
    )

    assert windowed["raster"]["width"] < whole["raster"]["width"]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `bin/test tests/test_qc_file.py -v`
Expected: FAIL — `file_raster_metrics` takes a `Path` and passes it to `gdalinfo` raw.

- [ ] **Step 3: Widen `file_raster_metrics`**

In `llm_gis/qc_collect.py`, add `gdal_uri` and `is_remote` to the `common` import, add
`from llm_gis.raster import window_vrt`, and change the signature and first lines:

```python
def file_raster_metrics(
    source: str | Path,
    exact_stats: bool,
    bbox: dict[str, float] | None = None,
    bbox_crs: str = "EPSG:4326",
) -> dict[str, Any]:
    """gdalinfo with PAM disabled: a .aux.xml write beside a read-only source would fail.

    With a bbox, statistics are measured over a VRT window rather than the whole raster,
    which is what makes a remote scene a QC source at all.
    """
    from llm_gis.common import work_root

    target = gdal_uri(str(source))
    if bbox:
        target = str(window_vrt(str(source), bbox, bbox_crs, None, work_root() / "raster" / "qc"))
    flag = "-stats" if exact_stats else "-approx_stats"
    env = {**os.environ, "GDAL_PAM_ENABLED": "NO"}
    payload = json.loads(run_command(["gdalinfo", "-json", flag, target], env=env))
```

The remainder of the function is unchanged.

- [ ] **Step 4: Widen `file_metrics` and `resolve_source`**

In `qc_collect.file_metrics`, change the signature to
`def file_metrics(path: str | Path, id_column: str | None, exact_stats: bool, bbox: dict | None = None) -> tuple[dict, dict]:`
and the dispatch:

```python
    text = str(path)
    kind = "raster" if is_remote(text) or Path(text).suffix.lower() in RASTER_SUFFIXES else "vector"
    metrics = (
        file_raster_metrics(text, exact_stats, bbox)
        if kind == "raster"
        else file_vector_metrics(Path(text), id_column)
    )
```

A remote URI is treated as a raster: Phase 7 gives no remote vector reader, and guessing
from a suffix that may be absent would be a worse answer than a clear one.

In `qc.resolve_source`, add a first branch:

```python
    if is_remote(ref):
        return {"kind": "file", "ref": ref}
```

and import `is_remote` from `llm_gis.common`. Thread an optional `bbox` through
`qc_report` into the `file_metrics` call.

- [ ] **Step 5: Run the tests**

Run: `bin/test tests/test_qc_file.py tests/test_qc_cli.py tests/test_qc_checks.py -v`
Expected: PASS.

- [ ] **Step 6: Add `--bbox` to the qc command**

In `llm_gis/cli.py`, `qc_cmd` gains
`bbox: str | None = typer.Option(None, "--bbox", help="Restrict raster QC to this AOI, minx,miny,maxx,maxy in EPSG:4326")`,
parsed with `_parse_bbox` into the dict shape `{"minx": ..., "miny": ..., "maxx": ..., "maxy": ...}` and passed to `qc_report`.

Verify: `bin/qc tests/fixtures/scene.tif --bbox 8.91,45.99,8.92,46.00`
Expected: `"qc_status": "ok"` with a raster block whose `width` is smaller than the
fixture's 512.

- [ ] **Step 7: Commit**

```bash
git add llm_gis/qc_collect.py llm_gis/qc.py llm_gis/cli.py tests/test_qc_file.py
git commit -m "feat: QC accepts a remote raster and an AOI window"
```

---

### Task 6: bin/preview

**Files:**
- Create: `llm_gis/preview.py`
- Modify: `llm_gis/cli.py` (add `preview`)
- Create: `bin/preview`
- Test: `tests/test_preview.py`

**Interfaces:**
- Consumes: `common.gdal_uri`, `common.reproject_bbox` (Tasks 1 and 3);
  `qc_collect.file_raster_metrics` and `qc_collect.file_vector_metrics` (Task 5).
- Produces: `preview.frame(dataset_bbox: dict, aoi_bbox: dict | None) -> dict` returning
  `{"bbox_4326": {...}, "size": [512, 512], "resampling": "nearest"}`;
  `preview.render(dataset: str, *, aoi: str | None = None, output: str | None = None) -> dict`
  writing `<output>.png` and `<output>.preview.json`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_preview.py`:

```python
"""Framing is pure and asserted directly; rendering is asserted on the files it writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_gis import preview

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))


def test_the_frame_is_the_union_of_dataset_and_aoi():
    frame = preview.frame(
        {"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0},
        {"minx": 5.0, "miny": 5.0, "maxx": 6.0, "maxy": 6.0},
    )

    assert frame["bbox_4326"]["minx"] <= 0.0
    assert frame["bbox_4326"]["maxx"] >= 6.0
    assert frame["size"] == [512, 512]


def test_the_frame_without_an_aoi_is_the_dataset_alone():
    frame = preview.frame({"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0}, None)

    assert frame["bbox_4326"]["maxx"] < 2.0


def test_the_frame_is_padded_and_never_zero_sized():
    """A point dataset has no width; a frame with no width cannot be rendered."""
    frame = preview.frame({"minx": 9.0, "miny": 45.0, "maxx": 9.0, "maxy": 45.0}, None)

    box = frame["bbox_4326"]
    assert box["maxx"] > box["minx"]
    assert box["maxy"] > box["miny"]


def test_rendering_a_raster_writes_a_png_and_a_sidecar(tmp_path):
    result = preview.render(str(FIXTURES / "scene.tif"), output=str(tmp_path / "scene"))

    png = Path(result["png"])
    sidecar = json.loads(Path(result["sidecar"]).read_text())

    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert sidecar["render"]["channels"] == {"r": "data", "g": "aoi", "b": "graticule"}
    assert sidecar["render"]["scale"]["min"] is not None
    assert sidecar["summary"]["aoi_intersects"] is None


def test_rendering_a_vector_writes_a_png(tmp_path):
    result = preview.render(str(FIXTURES / "aoi.gpkg"), output=str(tmp_path / "aoi"))

    assert Path(result["png"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert result["kind"] == "vector"


def test_a_disjoint_aoi_is_reported_in_the_sidecar(tmp_path):
    """The number the picture is meant to show, so the two can be compared."""
    result = preview.render(
        str(FIXTURES / "scene.tif"),
        aoi=str(FIXTURES / "aoi.gpkg"),
        output=str(tmp_path / "disjoint"),
    )

    sidecar = json.loads(Path(result["sidecar"]).read_text())
    assert sidecar["summary"]["aoi_intersects"] is False


def test_the_render_is_deterministic(tmp_path):
    first = preview.render(str(FIXTURES / "scene.tif"), output=str(tmp_path / "a"))
    second = preview.render(str(FIXTURES / "scene.tif"), output=str(tmp_path / "b"))

    assert Path(first["png"]).read_bytes() == Path(second["png"]).read_bytes()
```

The `aoi.gpkg` fixture sits at 10.0-10.3 E, 45.0-45.3 N and `scene.tif` at roughly
8.9-9.0 E, 45.97-46.02 N, so they are genuinely disjoint. That is what makes the
`test_a_disjoint_aoi_is_reported_in_the_sidecar` case real rather than contrived.

- [ ] **Step 2: Run them to make sure they fail**

Run: `bin/test tests/test_preview.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'llm_gis.preview'`.

- [ ] **Step 3: Write `llm_gis/preview.py`**

```python
"""A deterministic picture of a dataset, for a reader that has eyes.

Numbers hide three failures that a picture does not: coordinates given in the wrong
order, an AOI that misses the data entirely, and features nowhere near the AOI. The
frame is always EPSG:4326 with a drawn graticule, so all three are visible in one
image: wrong graticule cell, clear space between two shapes, or a small box beside a
sprawl.

Nothing here measures. Metrics come from qc_collect, the same collectors bin/qc judges.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_gis import qc_collect
from llm_gis.common import (
    ensure_workspace_dirs,
    gdal_uri,
    is_remote,
    reproject_bbox,
    run_command,
    utc_now,
    work_root,
)

WGS84 = "EPSG:4326"
SIZE = 512
PAD = 0.05
MIN_SPAN = 0.001
GRATICULE_DEGREES = 1
RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}


def _union(a: dict[str, float], b: dict[str, float] | None) -> dict[str, float]:
    if not b:
        return dict(a)
    return {
        "minx": min(a["minx"], b["minx"]),
        "miny": min(a["miny"], b["miny"]),
        "maxx": max(a["maxx"], b["maxx"]),
        "maxy": max(a["maxy"], b["maxy"]),
    }


def frame(dataset_bbox: dict[str, float], aoi_bbox: dict[str, float] | None) -> dict[str, Any]:
    """The rendered extent: the union, padded, squared, never zero-sized.

    Zero span is the degenerate case a single point or a single-row raster produces;
    a frame with no width cannot be rendered, so MIN_SPAN floors it.
    """
    box = _union(dataset_bbox, aoi_bbox)
    span = max(box["maxx"] - box["minx"], box["maxy"] - box["miny"], MIN_SPAN)
    pad = span * PAD
    cx = (box["minx"] + box["maxx"]) / 2
    cy = (box["miny"] + box["maxy"]) / 2
    half = span / 2 + pad
    return {
        "bbox_4326": {
            "minx": cx - half, "miny": cy - half, "maxx": cx + half, "maxy": cy + half,
        },
        "size": [SIZE, SIZE],
        "resampling": "nearest",
    }


def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["maxx"] < b["minx"] or b["maxx"] < a["minx"]
        or a["maxy"] < b["miny"] or b["maxy"] < a["miny"]
    )


def _kind(dataset: str) -> str:
    if is_remote(dataset):
        return "raster"
    return "raster" if Path(dataset).suffix.lower() in RASTER_SUFFIXES else "vector"


def _metrics(dataset: str, kind: str) -> dict[str, Any]:
    if kind == "raster":
        return qc_collect.file_raster_metrics(dataset, False)
    return qc_collect.file_vector_metrics(Path(dataset), None)


def _graticule(box: dict[str, float], destination: Path) -> Path:
    """Whole-degree lines as GeoJSON, computed rather than downloaded."""
    import math

    lines = []
    for x in range(math.floor(box["minx"]), math.ceil(box["maxx"]) + 1, GRATICULE_DEGREES):
        lines.append([[x, box["miny"]], [x, box["maxy"]]])
    for y in range(math.floor(box["miny"]), math.ceil(box["maxy"]) + 1, GRATICULE_DEGREES):
        lines.append([[box["minx"], y], [box["maxx"], y]])
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": c}}
            for c in lines
        ],
    }
    destination.write_text(json.dumps(payload), encoding="utf-8")
    return destination


def _blank(box: dict[str, float], destination: Path) -> Path:
    """One empty Byte channel on the frame's grid. Every channel shares this grid."""
    run_command([
        "gdal_create", "-q", "-outsize", str(SIZE), str(SIZE), "-bands", "1",
        "-ot", "Byte", "-burn", "0", "-a_srs", WGS84,
        "-a_ullr", str(box["minx"]), str(box["maxy"]), str(box["maxx"]), str(box["miny"]),
        str(destination),
    ])
    return destination


def _burn(source: str, channel: Path, work_dir: Path, name: str, outline: bool) -> None:
    """Reproject to 4326 and burn into a channel: an outline, or a fill."""
    prepared = work_dir / f"{name}.geojson"
    args = ["ogr2ogr", "-q", "-t_srs", WGS84, "-f", "GeoJSON"]
    if outline:
        args += ["-nlt", "MULTILINESTRING"]
    run_command([*args, str(prepared), gdal_uri(source)])
    run_command([
        "gdal_rasterize", "-q", "-b", "1", "-burn", "255", str(prepared), str(channel),
    ])


def _raster_channel(dataset: str, box: dict[str, float], scale: dict, work_dir: Path, name: str) -> Path:
    """The data, warped onto the frame's grid and scaled to Byte by measured bounds.

    The scale bounds come from the measured statistics, never from a per-run guess:
    that is what makes two renders of the same input identical byte for byte.
    """
    warped = work_dir / f"{name}.warped.tif"
    run_command([
        "gdalwarp", "-q", "-overwrite", "-t_srs", WGS84,
        "-te", str(box["minx"]), str(box["miny"]), str(box["maxx"]), str(box["maxy"]),
        "-ts", str(SIZE), str(SIZE), "-r", "nearest",
        gdal_uri(dataset), str(warped),
    ])
    channel = work_dir / f"{name}.red.tif"
    low, high = scale["min"], scale["max"]
    if low is None or high is None or low == high:
        low, high = 0.0, 1.0
    run_command([
        "gdal_translate", "-q", "-ot", "Byte",
        "-scale", str(low), str(high), "0", "255",
        "-b", "1", str(warped), str(channel),
    ])
    return channel


def render(
    dataset: str,
    *,
    aoi: str | None = None,
    output: str | None = None,
) -> dict[str, Any]:
    """Write a PNG and its sidecar. Same input, same bytes.

    Three single-band channels are built on one grid and stacked with
    `gdalbuildvrt -separate`, which is a description rather than a copy, then written
    once as PNG. Nothing is composited in Python and no image library is needed.
    """
    ensure_workspace_dirs()
    kind = _kind(dataset)
    metrics = _metrics(dataset, kind)
    data_bbox = reproject_bbox(metrics["bbox"], metrics["crs"], WGS84)

    aoi_bbox = None
    if aoi:
        aoi_metrics = _metrics(aoi, _kind(aoi))
        aoi_bbox = reproject_bbox(aoi_metrics["bbox"], aoi_metrics["crs"], WGS84)

    computed = frame(data_bbox, aoi_bbox)
    box = computed["bbox_4326"]

    stem = Path(output) if output else work_root() / "preview" / Path(dataset).stem
    stem.parent.mkdir(parents=True, exist_ok=True)
    work_dir = stem.parent
    name = stem.name

    scale = {"min": None, "max": None}
    if kind == "raster":
        band = ((metrics.get("raster") or {}).get("bands") or [{}])[0]
        scale = {"min": band.get("min"), "max": band.get("max")}
        red = _raster_channel(dataset, box, scale, work_dir, name)
    else:
        red = _blank(box, work_dir / f"{name}.red.tif")
        _burn(dataset, red, work_dir, f"{name}.data", outline=False)

    green = _blank(box, work_dir / f"{name}.green.tif")
    if aoi:
        _burn(aoi, green, work_dir, f"{name}.aoi", outline=True)

    blue = _blank(box, work_dir / f"{name}.blue.tif")
    graticule = _graticule(box, work_dir / f"{name}.graticule.geojson")
    run_command([
        "gdal_rasterize", "-q", "-b", "1", "-burn", "255", str(graticule), str(blue),
    ])

    stacked = work_dir / f"{name}.rgb.vrt"
    run_command([
        "gdalbuildvrt", "-q", "-separate", str(stacked), str(red), str(green), str(blue),
    ])
    png = stem.with_suffix(".png")
    run_command(["gdal_translate", "-q", "-of", "PNG", str(stacked), str(png)])

    sidecar_payload = {
        "dataset": {"uri": dataset, "kind": kind},
        "frame": computed,
        "render": {
            "channels": {"r": "data", "g": "aoi", "b": "graticule"},
            "scale": scale,
            "graticule_degrees": GRATICULE_DEGREES,
        },
        "summary": {
            "crs": metrics["crs"],
            "bbox": metrics["bbox"],
            "bbox_4326": data_bbox,
            "bands": (metrics.get("raster") or {}).get("bands") if kind == "raster" else None,
            "aoi_intersects": None if not aoi_bbox else _intersects(data_bbox, aoi_bbox),
        },
        "created_at": utc_now(),
    }
    sidecar = stem.with_suffix(".preview.json")
    sidecar.write_text(json.dumps(sidecar_payload, indent=2, sort_keys=True), encoding="utf-8")

    return {"png": str(png), "sidecar": str(sidecar), "kind": kind, **sidecar_payload}
```

The `gdalbuildvrt -separate` stack was verified in the container on 2026-09-10: three
512x512 Byte channels became a valid three-band VRT and an 842-byte PNG whose first eight
bytes are the PNG signature.

Two details that will bite if changed. `_blank` gives every channel the same grid, so the
VRT stack needs no resampling and the AOI cannot drift by a pixel against the data. And
`_raster_channel` floors a degenerate scale (a constant-valued raster, where min equals
max) to 0-1 rather than dividing by zero — the committed `scene.tif` fixture is exactly
that case, so the tests exercise it.

- [ ] **Step 4: Run the tests**

Run: `bin/test tests/test_preview.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Add the CLI command and wrapper**

In `llm_gis/cli.py`, import `from llm_gis.preview import render as preview_render` and add:

```python
@app.command("preview")
@handle_errors
def preview_cmd(
    dataset: str = typer.Argument(..., help="Path or URI to a vector or raster"),
    aoi: str | None = typer.Option(None, "--aoi", help="Vector dataset to draw as an outline"),
    output: str | None = typer.Option(None, "--output", help="Path stem; .png and .preview.json are written"),
) -> None:
    _emit("preview", preview_render(dataset, aoi=aoi, output=output))
```

```bash
sed 's/llm-gis inspect/llm-gis preview/' bin/inspect > bin/preview
chmod +x bin/preview
```

Verify: `bin/preview tests/fixtures/scene.tif --output /data/outgoing/scene`
Expected: `/data/outgoing/scene.png` and `/data/outgoing/scene.preview.json` exist. Open
the PNG and confirm it shows a bright square with graticule lines across it.

- [ ] **Step 6: Commit**

```bash
git add llm_gis/preview.py llm_gis/cli.py bin/preview tests/test_preview.py
git commit -m "feat: bin/preview renders a deterministic PNG with AOI and graticule"
```

---

### Task 7: Documentation and the live field test

**Files:**
- Create: `tests/live/test_raster_remote.py`
- Modify: `README.md`, `AGENTS.md`, `.claude/skills/hot-start/SKILL.md`
- Modify: `docs/plans/2026-09-04_improvement_plan_revised.md` (D8, D9; O6/O8 status)

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: no code interface. The live test is the phase's done-when.

- [ ] **Step 1: Write the live test**

Create `tests/live/test_raster_remote.py`:

```python
"""Example 3, against a live Earth Search COG. Excluded from the default run.

Run with: bin/test tests/live/test_raster_remote.py -m live -v
"""

from __future__ import annotations

import pytest

from llm_gis import raster
from llm_gis.inspect import inspect_dataset

HREF = (
    "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/"
    "32/T/MR/2023/6/S2A_32TMR_20230605_0_L2A/B04.tif"
)
AOI = (8.90, 45.95, 8.96, 46.00)

pytestmark = pytest.mark.live


def test_remote_inspect_reads_the_header_only():
    report = inspect_dataset(HREF)

    assert report["dataset_kind"] == "raster"
    assert report["size"] == [10980, 10980]
    assert "32632" in report["detected_crs"]


def test_a_window_read_does_not_download_the_scene(tmp_path):
    destination = tmp_path / "aoi.tif"
    result = raster.window(HREF, bbox=AOI, stats=True, output=str(destination))

    assert result["aoi_intersects"] is True
    assert result["bands"][0]["mean"] is not None
    # The scene is roughly 150 MB; the window is a small fraction of it.
    assert destination.stat().st_size < 5_000_000
```

Run: `bin/test tests/live/test_raster_remote.py -m live -v`
Expected: PASS, both tests, in well under a minute.

- [ ] **Step 2: Confirm the default suite still excludes it**

Run: `bin/test tests/ -v`
Expected: PASS, with the live file deselected.

- [ ] **Step 3: Run Example 3 end to end by hand and record it**

```bash
bin/catalog-search --collection sentinel-2-l2a --bbox 8.90,45.95,8.96,46.00 --limit 1
bin/catalog-assets <item-url> --media-type image/tiff
bin/inspect <B04 href>
bin/raster-window <B04 href> --bbox 8.90,45.95,8.96,46.00 --stats --output /data/outgoing/aoi_b04.tif
bin/preview /data/outgoing/aoi_b04.tif
```

Confirm each step returns `"status": "ok"`, that `catalog-assets` now reports
`"readers": ["gdal", "postgis"]` where it previously reported `[]`, and that
`aoi_b04.tif` is well under a megabyte. Write the transcript to
`docs/reports/2026-09-10_phase7_field_test.md` following whatever shape the existing
Phase 4 report in `docs/reports/` uses.

- [ ] **Step 4: Update the documentation**

- `README.md`: add `bin/raster-window` and `bin/preview` to the command list, one line
  each. Keep it concise, as the project instructions require.
- `AGENTS.md`: add the engine-choice guidance — GDAL for raster, and specifically that a
  remote COG is read in place rather than staged; no engine choice exists for raster
  beyond "window it, or ingest it".
- `.claude/skills/hot-start/SKILL.md`: add the raster module's technical context, per the
  project instruction that new modules add their context there. Cover: `/vsicurl`, the
  VRT window, that `--output` is the only thing that writes pixels, and that
  `gdal raster zonal-stats` is the one provisional-CLI call.
- `docs/plans/2026-09-04_improvement_plan_revised.md`: append D8 and D9 to the Departures
  section, verbatim from the spec's "Decisions for the log", and move O6 and O8 in the
  classification table from PLANNED Phase 7 to DONE.

- [ ] **Step 5: Commit**

```bash
git add tests/live/test_raster_remote.py README.md AGENTS.md \
        .claude/skills/hot-start/SKILL.md docs/plans/2026-09-04_improvement_plan_revised.md \
        docs/reports/2026-09-10_phase7_field_test.md
git commit -m "docs: Phase 7 commands, decisions D8 and D9, and the Example 3 field test"
```

---

## Done when

`bin/catalog-search` finds a Sentinel-2 item, `bin/catalog-assets` reports its COG as
readable, `bin/inspect` reads the header remotely, `bin/raster-window` writes an AOI
COG under a megabyte from a 150 MB scene with statistics, and `bin/preview` renders it —
with `bin/test tests/` green and `tests/live/test_raster_remote.py` passing under `-m live`.
