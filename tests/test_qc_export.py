"""Export attaches QC to what it wrote, and resolves its reference in the
documented order: --compare-to, then --table, then nothing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from llm_gis import exporter
from llm_gis.common import run_command as real_run_command
from llm_gis.errors import GisError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path / "work"))


@pytest.fixture
def written(monkeypatch, tmp_path):
    """Skip the ogr2ogr call; put a real GeoPackage where export would write one."""
    destination = tmp_path / "result.gpkg"

    def fake_run_command(cmd, **kwargs):
        if cmd[0] == "ogr2ogr":
            shutil.copy2(FIXTURES / "aoi.gpkg", destination)
            return ""
        return real_run_command(cmd, **kwargs)

    monkeypatch.setattr(exporter, "run_command", fake_run_command)
    return destination


def test_export_attaches_a_qc_block_by_default(written, monkeypatch):
    monkeypatch.setattr(exporter, "reference_for", lambda ref: {"ref": ref, "crs": None, "bbox": None})
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


def test_expect_non_empty_passes_when_features_are_present(written, monkeypatch):
    monkeypatch.setattr(exporter, "reference_for", lambda ref: {"ref": ref, "crs": None, "bbox": None})
    result = exporter.export_result(written, "gpkg", table="raw_x.aoi", qc=True, expect_non_empty=True)
    assert result["feature_count"] == 4


def test_expect_non_empty_raises_on_an_empty_result(tmp_path, monkeypatch):
    destination = tmp_path / "empty.gpkg"

    def fake_run_command(cmd, **kwargs):
        if cmd[0] == "ogr2ogr":
            real_run_command(
                ["ogr2ogr", "-f", "GPKG", str(destination), str(FIXTURES / "aoi.gpkg"), "-where", "1=0"]
            )
            return ""
        return real_run_command(cmd, **kwargs)

    monkeypatch.setattr(exporter, "run_command", fake_run_command)
    monkeypatch.setattr(exporter, "reference_for", lambda ref: {"ref": ref, "crs": None, "bbox": None})
    with pytest.raises(GisError) as excinfo:
        exporter.export_result(destination, "gpkg", table="raw_x.aoi", qc=False, expect_non_empty=True)
    assert excinfo.value.code == "EMPTY_EXPORT_RESULT"


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
