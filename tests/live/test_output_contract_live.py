"""Live coverage for the output contract: every command's envelope, and the
counts/CRS that ingest-vector, run-sql and export now report about what they
actually produced. Requires the compose stack; deselected by default.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import psycopg
import pytest
from typer.testing import CliRunner

from llm_gis.cli import app
from llm_gis.common import db_connect, sanitize_identifier

FIXTURES = Path(__file__).parent.parent / "fixtures"
OUTGOING = Path("/data/outgoing")
OUTGOING_DIR_NAME = "_live_test_output_contract"
TABLE_NAME = "aoi_contract"


@pytest.fixture
def contract_paths(monkeypatch, tmp_path):
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


def _invoke_ok(runner: CliRunner, args: list[str]) -> dict:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


@pytest.mark.live
def test_pipeline_results_carry_the_envelope_and_real_counts(contract_paths):
    incoming_path, outgoing_dir, state = contract_paths
    runner = CliRunner()

    stage_result = _invoke_ok(runner, ["stage", str(incoming_path)])
    assert stage_result["status"] == "ok"
    assert stage_result["command"] == "stage"
    ingest_id = stage_result["ingest_id"]
    state["ingest_id"] = ingest_id
    sid = sanitize_identifier(ingest_id)

    ingest_result = _invoke_ok(
        runner,
        [
            "ingest-vector",
            stage_result["staged_item"],
            "--table",
            TABLE_NAME,
            "--ingest-id",
            ingest_id,
        ],
    )
    assert ingest_result["status"] == "ok"
    assert ingest_result["command"] == "ingest-vector"
    assert ingest_result["feature_count"] == 4
    assert ingest_result["invalid_before"] == 0
    assert ingest_result["invalid_after"] == 0

    sql_path = Path("/data/work/tmp") / f"{ingest_id}_contract.sql"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(
        f"CREATE SCHEMA IF NOT EXISTS analysis_{sid};\n"
        f"CREATE TABLE analysis_{sid}.aoi_area AS\n"
        f"SELECT id, name, ST_Area(geom::geography) AS area_m2, geom\n"
        f"FROM raw_{sid}.{TABLE_NAME};\n",
        encoding="utf-8",
    )
    run_sql_result = _invoke_ok(
        runner, ["run-sql", str(sql_path), "--ingest-id", ingest_id]
    )
    sql_path.unlink(missing_ok=True)
    assert run_sql_result["status"] == "ok"
    assert run_sql_result["command"] == "run-sql"
    assert run_sql_result["schema"] == f"analysis_{sid}"
    assert {"table": "aoi_area", "row_count": 4} in run_sql_result["tables"]

    output_path = outgoing_dir / "aoi_area.gpkg"
    export_result = _invoke_ok(
        runner,
        [
            "export",
            str(output_path),
            "--format",
            "gpkg",
            "--table",
            f"analysis_{sid}.aoi_area",
        ],
    )
    assert export_result["status"] == "ok"
    assert export_result["command"] == "export"

    gdf = gpd.read_file(output_path)
    assert export_result["feature_count"] == len(gdf) == 4
    assert export_result["crs"] == f"EPSG:{gdf.crs.to_epsg()}"

    describe_result = _invoke_ok(
        runner, ["describe-table", f"analysis_{sid}.aoi_area"]
    )
    assert describe_result["status"] == "ok"
    assert describe_result["command"] == "describe-table"

    list_result = _invoke_ok(runner, ["list-ingestions", "--limit", "5"])
    assert list_result["status"] == "ok"
    assert list_result["command"] == "list-ingestions"

    doctor_result = _invoke_ok(runner, ["doctor"])
    assert doctor_result["status"] == "ok"
    assert doctor_result["command"] == "doctor"
