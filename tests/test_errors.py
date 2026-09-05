import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from llm_gis.cli import app
from llm_gis.common import ensure_child_path, run_command
from llm_gis.describe import describe_table
from llm_gis.errors import (
    COMMAND_FAILED,
    INPUT_NOT_FOUND,
    PATH_OUTSIDE_ROOT,
    TABLE_NOT_FOUND,
    UNEXPECTED,
    GisError,
)
from llm_gis.inspect import inspect_dataset

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))


def test_to_dict_shape():
    error = GisError("SOME_CODE", "something failed", "do something about it")
    assert error.to_dict() == {
        "status": "error",
        "code": "SOME_CODE",
        "message": "something failed",
        "suggested_action": "do something about it",
    }


def test_ensure_child_path_outside_root_raises(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "file.gpkg"

    with pytest.raises(GisError) as excinfo:
        ensure_child_path(outside, root)
    assert excinfo.value.code == PATH_OUTSIDE_ROOT


def test_run_command_failure_raises_gis_error_with_stderr():
    with pytest.raises(GisError) as excinfo:
        run_command(["ls", "/no/such/path/at/all"])
    error = excinfo.value
    assert error.code == COMMAND_FAILED
    assert error.details["stderr"]
    assert error.to_dict()["details"]["stderr"], "stderr must survive into the JSON the caller sees"


def test_inspect_dataset_missing_path_raises_input_not_found():
    with pytest.raises(GisError) as excinfo:
        inspect_dataset(FIXTURES / "does-not-exist.gpkg")
    assert excinfo.value.code == INPUT_NOT_FOUND


def test_cli_bad_path_exits_one_with_json_error_on_stderr():
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "/no/such/path/at/all.gpkg"])

    assert result.exit_code == 1
    assert result.stdout == ""
    payload = json.loads(result.stderr)
    assert payload["code"] == INPUT_NOT_FOUND


@pytest.mark.live
def test_describe_table_raises_for_a_missing_table():
    """An absent table must not read as an existing empty one."""
    with pytest.raises(GisError) as caught:
        describe_table("raw_does_not_exist", "nothing")
    assert caught.value.code == TABLE_NOT_FOUND


def test_unexpected_exceptions_are_still_json(tmp_path):
    """Nothing may reach the caller as a traceback."""
    sql = tmp_path / "probe.sql"
    sql.write_text("SELECT 1;", encoding="utf-8")
    result = CliRunner().invoke(app, ["run-sql", str(sql), "--ingest-id", "---"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert json.loads(result.stderr)["code"] == UNEXPECTED


def test_command_failure_redacts_the_password(monkeypatch):
    """The DSN reaches machine-readable output, so the password must not."""
    with pytest.raises(GisError) as caught:
        run_command(["false", "PG:host=db password=hunter2"])
    payload = json.dumps(caught.value.to_dict())
    assert "hunter2" not in payload
    assert "password=***" in payload
