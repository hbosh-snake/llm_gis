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
