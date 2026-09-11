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
    payload = _run_ok(["plan", "analyse", "/data/incoming/b.parquet"])
    assert payload["strategy"] is None
    assert payload["steps"] == []
    assert payload["blocked_by"]["code"] == "NO_CONVERSION_PATH"


def test_materialising_a_parquet_source_converts_through_geopackage():
    """The conversion gap duck-query --format geopackage closes."""
    payload = _run_ok(["plan", "query", "/data/incoming/b.parquet", "--materialise"])
    assert payload["strategy"] == "postgis"
    assert payload["blocked_by"] is None
    assert [s["command"] for s in payload["steps"]] == ["duck-query", "ingest-vector", "export"]
    assert "--format" in payload["steps"][0]["argv"]
    assert "geopackage" in payload["steps"][0]["argv"]


def test_an_impossible_override_exits_one_with_a_code():
    result = CliRunner().invoke(app, ["plan", "query", "analysis_aoi.result",
                                      "--engine", "duckdb"])
    assert result.exit_code == 1
    assert json.loads(result.stderr)["code"] == "UNSUPPORTED_FORMAT"


def test_the_planner_never_touches_the_source():
    """Every path above names a file that does not exist, and none of them failed."""
    payload = _run_ok(["plan", "query", "/nowhere/at/all/aoi.gpkg"])
    assert payload["strategy"] == "duckdb"
