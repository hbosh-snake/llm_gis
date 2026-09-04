"""Live regression test for the local-file -> PostGIS -> analysis -> export workflow.

Requires the compose stack (`docker compose up -d db`) and runs inside the
`agent` container, where `/data/outgoing` and `/data/work` are the real
mounts. `/data/incoming` is read-only, so the incoming root is redirected
to a writable temp directory via `LLM_GIS_INCOMING_ROOT` for this test.
Deselected by default; run with `bin/test -m live`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import geopandas as gpd
import psycopg
import pytest

from llm_gis.common import db_connect, sanitize_identifier
from llm_gis.exporter import export_result
from llm_gis.ingest_vector import ingest_vector
from llm_gis.run_sql import run_sql_file
from llm_gis.stage import stage_input

FIXTURES = Path(__file__).parent.parent / "fixtures"
OUTGOING = Path("/data/outgoing")

OUTGOING_DIR_NAME = "_live_test_roundtrip"
TABLE_NAME = "aoi_live"


@pytest.fixture
def roundtrip_paths(monkeypatch, tmp_path):
    incoming_root = tmp_path / "incoming"
    incoming_root.mkdir()
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(incoming_root))

    incoming_path = incoming_root / "aoi.gpkg"
    outgoing_dir = OUTGOING / OUTGOING_DIR_NAME
    shutil.copy2(FIXTURES / "aoi.gpkg", incoming_path)

    state: dict = {}
    yield incoming_path, outgoing_dir, state

    shutil.rmtree(outgoing_dir, ignore_errors=True)

    ingest_id = state.get("ingest_id")
    if ingest_id:
        sid = sanitize_identifier(ingest_id)
        shutil.rmtree(Path("/data/work/staging") / ingest_id, ignore_errors=True)
        (Path("/data/work/reports") / f"{ingest_id}.json").unlink(missing_ok=True)
        shutil.rmtree(Path("/data/work/logs") / sid, ignore_errors=True)
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE;").format(
                        psycopg.sql.Identifier(f"analysis_{sid}")
                    )
                )
                cur.execute(
                    psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE;").format(
                        psycopg.sql.Identifier(f"raw_{sid}")
                    )
                )
                cur.execute("DELETE FROM meta.ingestions WHERE ingest_id = %s;", (ingest_id,))


@pytest.mark.live
def test_local_file_to_postgis_to_export_roundtrip(roundtrip_paths):
    incoming_path, outgoing_dir, state = roundtrip_paths

    stage_report = stage_input(incoming_path)
    ingest_id = stage_report["ingest_id"]
    state["ingest_id"] = ingest_id
    sid = sanitize_identifier(ingest_id)

    ingest_report = ingest_vector(
        input_path=Path(stage_report["staged_item"]),
        table=TABLE_NAME,
        ingest_id=ingest_id,
        src_crs=None,
        dst_crs=None,
        schema=None,
    )
    assert ingest_report["schema"] == f"raw_{sid}"

    sql_text = (
        f"CREATE SCHEMA IF NOT EXISTS analysis_{sid};\n"
        f"CREATE TABLE analysis_{sid}.aoi_area AS\n"
        f"SELECT id, name, ST_Area(geom::geography) AS area_m2, geom\n"
        f"FROM raw_{sid}.{TABLE_NAME};\n"
    )
    sql_path = Path("/data/work/tmp") / f"{ingest_id}_roundtrip.sql"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(sql_text, encoding="utf-8")
    run_sql_file(sql_path, ingest_id)
    sql_path.unlink(missing_ok=True)

    output_path = outgoing_dir / "aoi_area.gpkg"
    export_result(output_path, "gpkg", table=f"analysis_{sid}.aoi_area")

    gdf = gpd.read_file(output_path)
    assert len(gdf) == 4
    assert gdf.crs.to_epsg() == 4326
