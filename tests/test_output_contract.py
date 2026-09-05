"""Every successful command result carries a stable status/command envelope
and reports what it actually produced. See docs/llm/OUTPUT_SCHEMA.md.
"""

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


def _run_ok(runner: CliRunner, args: list[str]) -> dict:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_inspect_result_carries_the_envelope():
    payload = _run_ok(CliRunner(), ["inspect", str(FIXTURES / "aoi.gpkg")])
    assert payload["status"] == "ok"
    assert payload["command"] == "inspect"


def test_inspect_with_ingest_id_still_carries_the_envelope():
    payload = _run_ok(
        CliRunner(), ["inspect", str(FIXTURES / "aoi.gpkg"), "--ingest-id", "envelope-probe"]
    )
    assert payload["status"] == "ok"
    assert payload["command"] == "inspect"


def test_output_schema_lists_every_bin_command():
    """OUTPUT_SCHEMA.md must not silently drift from the commands that exist."""
    bin_dir = Path(__file__).parent.parent / "bin"
    excluded = {"test", "_env.sh"}
    commands = sorted(p.name for p in bin_dir.iterdir() if p.name not in excluded)

    schema_text = (Path(__file__).parent.parent / "docs" / "llm" / "OUTPUT_SCHEMA.md").read_text(
        encoding="utf-8"
    )
    for command in commands:
        assert f"bin/{command}" in schema_text, f"OUTPUT_SCHEMA.md is missing {command}"


def test_usage_errors_stay_with_typer():
    """A malformed argument is the caller's typo, not an internal failure: exit 2."""
    result = CliRunner().invoke(app, ["describe-table", "no-dot-here"])
    assert result.exit_code == 2


def test_export_of_a_non_spatial_layer_still_succeeds(tmp_path, monkeypatch):
    """The read-back is reporting, not validation, and must not fail a written file."""
    from llm_gis.exporter import _written_vector_summary

    csv = tmp_path / "plain.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    count, crs = _written_vector_summary(csv)
    assert crs is None
