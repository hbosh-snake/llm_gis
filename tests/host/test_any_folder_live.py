"""Small external-folder acceptance cases; run with uv run pytest tests/host -m live."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import geopandas as gpd
import pytest
from shapely.geometry import box

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.live


@pytest.fixture
def external_job(tmp_path):
    caller = tmp_path / "client folder with spaces"
    sources = tmp_path / "second input folder"
    caller.mkdir()
    sources.mkdir()
    # An unrelated project must not replace the backend's Python environment.
    (caller / "pyproject.toml").write_text(
        '[project]\nname = "unrelated-client"\nversion = "0.0.0"\nrequires-python = ">=99"\n'
    )
    parcels = caller / "parcels.gpkg"
    boundary = sources / "boundary.gpkg"
    gpd.GeoDataFrame(
        {"parcel": list(range(1, 13))},
        geometry=[box(4000000 + n * 200, 3000000,
                      4000000 + n * 200 + n * 10, 3000010) for n in range(1, 13)],
        crs="EPSG:3035",
    ).to_file(parcels, layer="parcels")
    gpd.GeoDataFrame(
        {"id": [1]}, geometry=[box(4000000, 3000000, 4003000, 3000005)],
        crs="EPSG:3035",
    ).to_file(boundary, layer="boundary")
    scene = caller / "scene.tif"
    shutil.copy2(REPO / "tests/fixtures/scene.tif", scene)
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (parcels, boundary, scene)}
    jobs = tmp_path / "jobs"
    ingestions = []

    def call(*args):
        result = subprocess.run(
            [str(REPO / "bin/llm-gis"), *map(str, args)], cwd=caller,
            env=os.environ | {"LLM_GIS_JOBS_ROOT": str(jobs)},
            text=True, capture_output=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if args[0] == "ingest-vector":
            ingestions.append(payload)
        return payload

    try:
        yield caller, boundary, jobs, call
    finally:
        # Remove only schemas and metadata created by this fixture's successful ingests.
        if ingestions:
            statements = []
            for item in ingestions:
                ingest_id = item["ingest_id"]
                statements.extend([
                    f'DROP SCHEMA IF EXISTS "analysis_{ingest_id}" CASCADE;',
                    f'DROP SCHEMA IF EXISTS "{item["schema"]}" CASCADE;',
                    f"DELETE FROM meta.ingestions WHERE ingest_id = '{ingest_id}';",
                ])
            cleanup = subprocess.run(
                ["docker", "compose", "exec", "-T", "db", "psql", "-U",
                 os.environ.get("POSTGRES_USER", "gis"), "-d",
                 os.environ.get("POSTGRES_DB", "gis"), "-v", "ON_ERROR_STOP=1"],
                cwd=REPO, input="\n".join(statements), text=True, capture_output=True,
                timeout=30,
            )
            assert cleanup.returncode == 0, cleanup.stderr
        assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes} == hashes
        assert not list(jobs.glob("*/tmp"))


def test_external_count_ranking_and_clip(external_job):
    caller, boundary, _, call = external_job
    assert call("inspect", "parcels.gpkg")["crs_status"] == "ok"
    assert call("inspect", boundary)["crs_status"] == "ok"
    parcels = call("ingest-vector", "parcels.gpkg", "--table", "parcels")
    mask = call("ingest-vector", boundary, "--table", "boundary")
    source = f'{parcels["schema"]}.parcels'
    boundary_table = f'{mask["schema"]}.boundary'
    call("describe-table", source)
    call("describe-table", boundary_table)
    count = call("query-sql", "--sql",
                 f"SELECT count(*), sum(ST_Area(geom)) FROM {source}")
    assert count["rows"] == [[12, 7800.0]]
    assert count["truncated"] is False
    ranking = call("query-sql", "--sql", f"SELECT parcel, ST_Area(geom) AS area_m2 "
                   f"FROM {source} ORDER BY area_m2 DESC, fid LIMIT 10")
    assert ranking["rows"] == [[n, n * 100.0] for n in range(12, 2, -1)]
    assert ranking["truncated"] is False
    assert not (caller / "results").exists()

    clipped = call(
        "export", "results/clipped.gpkg", "--format", "gpkg", "--sql",
        f"SELECT p.fid, p.parcel, ST_Intersection(p.geom, b.geom) AS geom "
        f"FROM {source} p JOIN {boundary_table} b ON ST_Intersects(p.geom, b.geom)",
        "--compare-to", source, "--expect-non-empty",
    )
    output = caller / "results/clipped.gpkg"
    assert clipped["output_path"] == str(output)
    assert clipped["qc"]["warnings"] == []
    frame = gpd.read_file(output).sort_values("parcel")
    assert frame.crs.to_epsg() == 3035
    assert frame["parcel"].tolist() == list(range(1, 13))
    assert frame.area.tolist() == [n * 50.0 for n in range(1, 13)]
    for n, geometry in zip(range(1, 13), frame.geometry):
        assert geometry.equals(box(4000000 + n * 200, 3000000,
                                   4000000 + n * 210, 3000005))
    assert output.stat().st_uid == os.getuid()


def test_concurrent_vector_jobs_have_distinct_schemas_and_outputs(external_job):
    caller, _, jobs, call = external_job

    def run(index):
        report = call("ingest-vector", "parcels.gpkg", "--table", "parcels")
        output = call("export", f"results/job-{index}.gpkg", "--format", "gpkg",
                      "--table", f'{report["schema"]}.parcels', "--expect-non-empty")
        return report, output

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert len({report["ingest_id"] for report, _ in results}) == 2
    assert len({report["schema"] for report, _ in results}) == 2
    assert len(list(jobs.iterdir())) == 4
    for index, (_, output) in enumerate(results):
        assert output["qc"]["warnings"] == []
        frame = gpd.read_file(caller / f"results/job-{index}.gpkg")
        assert len(frame) == 12
        assert frame.crs.to_epsg() == 3035
        assert frame.area.sum() == 7800.0


def test_concurrent_raster_windows_use_separate_workspaces(external_job):
    caller, _, jobs, call = external_job

    def run(index):
        return call("raster-window", "scene.tif", "--bbox", "7.72,46.01,7.76,46.03",
                    "--output", f"results/window-{index}.tif")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    windows = list(jobs.glob("*/raster/window/window.vrt"))
    assert len(windows) == 2
    assert windows[0].parents[2] != windows[1].parents[2]
    for index, result in enumerate(results):
        assert result["aoi_intersects"] is True
        assert result["bands"][0]["mean"] == 1200.0
        output = caller / f"results/window-{index}.tif"
        assert result["output"] == str(output)
        assert output.stat().st_uid == os.getuid()
    assert (caller / "results/window-0.tif").read_bytes() == (caller / "results/window-1.tif").read_bytes()
