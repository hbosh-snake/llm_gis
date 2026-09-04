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
