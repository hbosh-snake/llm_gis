"""The host launcher preserves caller paths while isolating writable work."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import sys

import pytest


REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "bin" / "llm-gis"


@dataclass
class FakeDocker:
    env: dict[str, str]
    record: Path


@pytest.fixture
def repo() -> Path:
    return REPO


@pytest.fixture
def fake_docker(tmp_path: Path) -> FakeDocker:
    fake_bin = tmp_path / "fake bin"
    fake_bin.mkdir()
    record = tmp_path / "docker record.json"
    executable = fake_bin / "docker"
    executable.write_text(
        f"""#!{sys.executable}
import json
import os
from pathlib import Path
import sys

record = Path(os.environ["FAKE_DOCKER_RECORD"])
record.write_text(json.dumps({{
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "env": {{
        "LLM_GIS_UID": os.environ.get("LLM_GIS_UID"),
        "LLM_GIS_GID": os.environ.get("LLM_GIS_GID"),
    }},
}}), encoding="utf-8")
sys.stdout.write(os.environ.get(
    "FAKE_DOCKER_STDOUT", '{{"status":"ok","command":"doctor"}}\\n'
))
sys.stderr.write(os.environ.get("FAKE_DOCKER_STDERR", ""))
raise SystemExit(int(os.environ.get("FAKE_DOCKER_EXIT", "0")))
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["FAKE_DOCKER_RECORD"] = str(record)
    env["LLM_GIS_JOBS_ROOT"] = str(tmp_path / "jobs")
    return FakeDocker(env=env, record=record)


@pytest.fixture
def launcher_module() -> dict[str, object]:
    return runpy.run_path(str(LAUNCHER))


def run_launcher(
    fake_docker: FakeDocker,
    cwd: Path,
    *args: str,
    env_updates: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = fake_docker.env.copy()
    env.update(env_updates or {})
    return subprocess.run(
        [str(LAUNCHER), *args], cwd=cwd, env=env, text=True, capture_output=True
    )


def recorded(fake_docker: FakeDocker) -> dict[str, object]:
    return json.loads(fake_docker.record.read_text(encoding="utf-8"))


def volumes(argv: list[str]) -> list[str]:
    return [argv[index + 1] for index, item in enumerate(argv) if item == "--volume"]


def container_env(argv: list[str]) -> dict[str, str]:
    values = [argv[index + 1] for index, item in enumerate(argv) if item == "-e"]
    return dict(value.split("=", 1) for value in values)


def test_launcher_keeps_caller_cwd_and_selects_backend(
    fake_docker: FakeDocker, repo: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "client folder with spaces"
    cwd.mkdir()

    result = run_launcher(fake_docker, cwd, "doctor")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"status": "ok", "command": "doctor"}
    record = recorded(fake_docker)
    argv = record["argv"]
    assert record["cwd"] == str(cwd)
    assert argv[argv.index("--workdir") + 1] == str(cwd)
    assert argv[argv.index("--project-directory") + 1] == str(repo)
    assert argv[-7:] == [
        "uv", "run", "--project", "/workspace", "--quiet", "llm-gis", "doctor"
    ]
    assert record["env"] == {
        "LLM_GIS_UID": str(os.getuid()),
        "LLM_GIS_GID": str(os.getgid()),
    }


def test_launcher_resolves_repo_through_a_symlink(
    fake_docker: FakeDocker, repo: Path, tmp_path: Path
) -> None:
    cwd = tmp_path / "caller"
    cwd.mkdir()
    link = tmp_path / "installed" / "llm-gis"
    link.parent.mkdir()
    link.symlink_to(repo / "bin" / "llm-gis")

    result = subprocess.run(
        [str(link), "doctor"], cwd=cwd, env=fake_docker.env,
        text=True, capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    argv = recorded(fake_docker)["argv"]
    assert argv[argv.index("--project-directory") + 1] == str(repo)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["export", "--format", "gpkg", "nested/output.gpkg", "--table", "raw_x.a"],
            ["export", "--format", "gpkg", "{cwd}/nested/output.gpkg", "--table", "raw_x.a"],
        ),
        (
            ["raster-window", "scene.tif", "--bbox", "1,2,3,4", "--output=results/a.tif"],
            ["raster-window", "scene.tif", "--bbox", "1,2,3,4", "--output={cwd}/results/a.tif"],
        ),
        (
            ["duck-query", "input.parquet", "--output", "results/a.parquet"],
            ["duck-query", "input.parquet", "--output", "{cwd}/results/a.parquet"],
        ),
        (
            ["plan", "export", "input.gpkg", "--output", "results/a.gpkg"],
            ["plan", "export", "input.gpkg", "--output", "results/a.gpkg"],
        ),
    ],
)
def test_normalize_outputs_rewrites_only_known_output_operands(
    launcher_module: dict[str, object], tmp_path: Path, args: list[str], expected: list[str]
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    normalize_outputs = launcher_module["normalize_outputs"]

    actual = normalize_outputs(args, cwd)  # type: ignore[operator]

    assert actual == [item.format(cwd=cwd) for item in expected]


def test_preview_default_uses_backend_exact_dotted_stem_names(
    launcher_module: dict[str, object], tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    normalize_outputs = launcher_module["normalize_outputs"]
    output_paths = launcher_module["output_paths"]

    normalized = normalize_outputs(["preview", "parcels.v2.gpkg"], cwd)  # type: ignore[operator]

    assert normalized == [
        "preview", "parcels.v2.gpkg", "--output", str(cwd / "results" / "parcels.v2")
    ]
    assert output_paths(normalized, cwd) == [  # type: ignore[operator]
        cwd / "results" / "parcels.png",
        cwd / "results" / "parcels.preview.json",
    ]


def test_explicit_preview_output_is_absolute_and_keeps_input_unchanged(
    launcher_module: dict[str, object], tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    normalize_outputs = launcher_module["normalize_outputs"]

    normalized = normalize_outputs(  # type: ignore[operator]
        ["preview", "relative source.gpkg", "--output=images/map.v2"], cwd
    )

    assert normalized == [
        "preview", "relative source.gpkg", f"--output={cwd / 'images' / 'map.v2'}"
    ]


def test_path_discovery_mounts_external_sources_read_only_without_rewriting_values(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client with spaces"
    cwd.mkdir()
    source_dir = tmp_path / "source 'quoted'"
    source_dir.mkdir()
    source = source_dir / "input data.gpkg"
    source.write_text("fixture", encoding="utf-8")
    sql = "SELECT '/tmp/not-a-discovered-path', '$HOME', 'a b'"
    url = "https://example.test/a%20b.parquet"
    table = "analysis_abc.result"

    result = run_launcher(
        fake_docker, cwd, "qc", str(source), "--compare-to", table,
        "--id-column", sql, "--bbox=" + url,
    )

    assert result.returncode == 0, result.stderr
    argv = recorded(fake_docker)["argv"]
    assert argv[-7:] == [
        "qc", str(source), "--compare-to", table, "--id-column", sql, "--bbox=" + url,
    ]
    assert f"{source_dir}:{source_dir}:ro" in volumes(argv)
    assert all(not mount.endswith(":rw") for mount in volumes(argv) if str(source_dir) in mount)


def test_long_sql_like_argument_is_never_rewritten_or_path_parsed(
    launcher_module: dict[str, object], tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    sql = "SELECT '" + ("x" * 10_000) + "'"
    mounts_for = launcher_module["mounts_for"]

    with pytest.raises(Exception, match="overlaps"):
        mounts_for(  # type: ignore[operator]
            ["export", "out.gpkg", "--format", "gpkg", "--sql", sql],
            cwd,
            [cwd / "out.gpkg"],
            tmp_path / "work" / "job",
        )


def test_nested_output_folder_is_created_and_mounted_writable(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()

    result = run_launcher(
        fake_docker, cwd, "export", "new/nested/result.gpkg", "--format", "gpkg",
        "--table", "raw_a.source",
    )

    assert result.returncode == 0, result.stderr
    output_parent = cwd / "new" / "nested"
    assert output_parent.is_dir()
    argv = recorded(fake_docker)["argv"]
    assert "export" in argv
    assert str(output_parent / "result.gpkg") in argv
    assert f"{cwd}:{cwd}:ro" in volumes(argv)
    assert f"{output_parent}:{output_parent}:rw" in volumes(argv)


@pytest.mark.parametrize(
    ("stem", "collision"),
    [
        ("maps/parcels.v2", "maps/parcels.png"),
        ("maps/parcels.v2", "maps/parcels.preview.json"),
    ],
)
def test_preview_refuses_exact_dotted_stem_collisions_before_docker(
    fake_docker: FakeDocker, tmp_path: Path, stem: str, collision: str
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    target = cwd / collision
    target.parent.mkdir(parents=True)
    target.write_text("keep", encoding="utf-8")

    result = run_launcher(fake_docker, cwd, "preview", "source.gpkg", "--output", stem)

    assert result.returncode != 0
    assert not fake_docker.record.exists()
    error = json.loads(result.stderr)
    assert error["status"] == "error"
    assert error["code"] == "OUTPUT_EXISTS"
    assert str(target) in error["message"]


def test_export_refuses_existing_output_before_docker(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    output = cwd / "result.gpkg"
    output.write_text("keep", encoding="utf-8")

    result = run_launcher(fake_docker, cwd, "export", output.name, "--format", "gpkg")

    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == "keep"
    assert not fake_docker.record.exists()
    assert json.loads(result.stderr)["code"] == "OUTPUT_EXISTS"


@pytest.mark.parametrize(
    "root",
    ["/", "/data", "/workspace", "/opt", "/usr", "/etc", "/var", "/proc", "/sys", "/dev", "/root"],
)
def test_reserved_caller_mount_roots_are_refused(
    launcher_module: dict[str, object], tmp_path: Path, root: str
) -> None:
    mounts_for = launcher_module["mounts_for"]

    with pytest.raises(Exception) as excinfo:
        mounts_for(["doctor"], Path(root), [], tmp_path / "jobs" / "one")  # type: ignore[operator]

    assert getattr(excinfo.value, "code", None) == "MOUNT_REFUSED"
    assert root in str(excinfo.value)


def test_home_itself_and_a_file_directly_in_home_have_actionable_errors(
    launcher_module: dict[str, object], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    caller = home / "project"
    caller.mkdir(parents=True)
    source = home / "source.gpkg"
    source.write_text("fixture", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    mounts_for = launcher_module["mounts_for"]

    for args, cwd in [(["doctor"], home), (["inspect", str(source)], caller)]:
        with pytest.raises(Exception) as excinfo:
            mounts_for(args, cwd, [], tmp_path / "jobs" / "one")  # type: ignore[operator]
        assert getattr(excinfo.value, "code", None) == "MOUNT_REFUSED"
        assert str(home) in str(excinfo.value)
        assert "move it into a subfolder" in excinfo.value.suggested_action


@pytest.mark.parametrize("target", ["..", "../.."])
def test_parent_tokens_resolving_to_home_or_root_are_actionable(
    launcher_module: dict[str, object], monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path, target: str
) -> None:
    home = tmp_path / "home"
    caller = home / "project"
    caller.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    mounts_for = launcher_module["mounts_for"]
    if target == "../..":
        # Use a real root-resolving token while retaining a permitted caller.
        target = os.path.relpath("/", caller)

    with pytest.raises(Exception) as excinfo:
        mounts_for(["inspect", target], caller, [], tmp_path / "jobs" / "one")  # type: ignore[operator]

    assert getattr(excinfo.value, "code", None) == "MOUNT_REFUSED"
    assert "move it into a subfolder" in excinfo.value.suggested_action


def test_symlinked_output_parent_is_checked_at_its_real_reserved_root(
    launcher_module: dict[str, object], tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    link = cwd / "system-output"
    link.symlink_to("/var")
    normalize_outputs = launcher_module["normalize_outputs"]
    output_paths = launcher_module["output_paths"]
    mounts_for = launcher_module["mounts_for"]
    args = normalize_outputs(  # type: ignore[operator]
        ["export", "system-output/result.gpkg", "--format", "gpkg"], cwd
    )
    outputs = output_paths(args, cwd)  # type: ignore[operator]

    with pytest.raises(Exception) as excinfo:
        mounts_for(args, cwd, outputs, tmp_path / "jobs" / "one")  # type: ignore[operator]

    assert getattr(excinfo.value, "code", None) == "MOUNT_REFUSED"
    assert "/var" in str(excinfo.value)


def test_output_cannot_replace_source_read_only_mount(
    launcher_module: dict[str, object], tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    source_dir = cwd / "shared"
    source_dir.mkdir(parents=True)
    source = source_dir / "source.gpkg"
    source.write_text("fixture", encoding="utf-8")
    mounts_for = launcher_module["mounts_for"]

    with pytest.raises(Exception) as excinfo:
        mounts_for(  # type: ignore[operator]
            ["export", "shared/out.gpkg", "--format", "gpkg", "--compare-to", str(source)],
            cwd,
            [source_dir / "out.gpkg"],
            tmp_path / "jobs" / "one",
        )

    assert getattr(excinfo.value, "code", None) == "MOUNT_CONFLICT"
    assert "new subfolder" in excinfo.value.suggested_action


def test_writable_ancestor_of_external_source_is_refused(
    launcher_module: dict[str, object], tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    shared = tmp_path / "shared"
    source_dir = shared / "inputs"
    source_dir.mkdir(parents=True)
    source = source_dir / "source.gpkg"
    source.write_text("fixture", encoding="utf-8")
    mounts_for = launcher_module["mounts_for"]

    with pytest.raises(Exception) as excinfo:
        mounts_for(  # type: ignore[operator]
            ["export", str(shared / "out.gpkg"), "--format", "gpkg", "--compare-to", str(source)],
            cwd,
            [shared / "out.gpkg"],
            tmp_path / "jobs" / "one",
        )

    assert getattr(excinfo.value, "code", None) == "MOUNT_CONFLICT"


def test_job_tmp_is_removed_but_logs_reports_and_staging_are_retained(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()

    result = run_launcher(fake_docker, cwd, "doctor")

    assert result.returncode == 0, result.stderr
    values = container_env(recorded(fake_docker)["argv"])
    job = Path(values["LLM_GIS_WORK_ROOT"])
    assert Path(values["TMPDIR"]) == job / "tmp"
    assert not (job / "tmp").exists()
    assert (job / "logs").is_dir()
    assert (job / "reports").is_dir()
    assert (job / "staging").is_dir()
    assert (job / "logs" / "docker.stderr.log").exists()


def test_failure_also_removes_only_tmp_and_preserves_diagnostics(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    structured = {
        "status": "error", "code": "BACKEND_FAILED", "message": "bad source",
        "suggested_action": "fix the source", "details": {"source": "x"},
    }

    result = run_launcher(
        fake_docker, cwd, "inspect", "missing.gpkg",
        env_updates={"FAKE_DOCKER_EXIT": "7", "FAKE_DOCKER_STDOUT": "", "FAKE_DOCKER_STDERR": json.dumps(structured)},
    )

    assert result.returncode != 0
    assert json.loads(result.stderr) == structured
    values = container_env(recorded(fake_docker)["argv"])
    job = Path(values["LLM_GIS_WORK_ROOT"])
    assert not (job / "tmp").exists()
    assert (job / "staging").is_dir()
    assert (job / "logs" / "docker.stderr.log").read_text(encoding="utf-8") == json.dumps(structured)


def test_repeated_invocations_use_different_absolute_job_roots(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()

    first = run_launcher(fake_docker, cwd, "doctor")
    first_job = Path(container_env(recorded(fake_docker)["argv"])["LLM_GIS_WORK_ROOT"])
    second = run_launcher(fake_docker, cwd, "doctor")
    second_job = Path(container_env(recorded(fake_docker)["argv"])["LLM_GIS_WORK_ROOT"])

    assert first.returncode == second.returncode == 0
    assert first_job.is_absolute() and second_job.is_absolute()
    assert first_job != second_job


def test_jobs_root_can_be_overridden(fake_docker: FakeDocker, tmp_path: Path) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    jobs_root = tmp_path / "jobs root"

    result = run_launcher(
        fake_docker, cwd, "doctor", env_updates={"LLM_GIS_JOBS_ROOT": str(jobs_root)}
    )

    assert result.returncode == 0, result.stderr
    job = Path(container_env(recorded(fake_docker)["argv"])["LLM_GIS_WORK_ROOT"])
    assert job.parent == jobs_root


def test_a_retained_staged_path_can_be_a_later_read_only_source(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    first = run_launcher(fake_docker, cwd, "doctor")
    assert first.returncode == 0
    old_job = Path(container_env(recorded(fake_docker)["argv"])["LLM_GIS_WORK_ROOT"])
    staged = old_job / "staging" / "abc" / "source.gpkg"
    staged.parent.mkdir(parents=True)
    staged.write_text("fixture", encoding="utf-8")

    second = run_launcher(fake_docker, cwd, "inspect", str(staged))

    assert second.returncode == 0, second.stderr
    argv = recorded(fake_docker)["argv"]
    assert f"{staged.parent}:{staged.parent}:ro" in volumes(argv)
    assert argv[-1] == str(staged)


def test_non_json_docker_output_is_a_structured_launcher_error(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()

    result = run_launcher(
        fake_docker, cwd, "doctor", env_updates={"FAKE_DOCKER_STDOUT": "not json"}
    )

    assert result.returncode != 0
    error = json.loads(result.stderr)
    assert error["status"] == "error"
    assert error["code"] == "INVALID_DOCKER_OUTPUT"
    assert "details" in error


def test_missing_docker_is_a_structured_error(
    fake_docker: FakeDocker, tmp_path: Path
) -> None:
    cwd = tmp_path / "client"
    cwd.mkdir()
    env = fake_docker.env.copy()
    env["PATH"] = str(tmp_path / "empty-path")
    # Invoke uv explicitly so the launcher shebang does not consume the test PATH.
    uv = shutil.which("uv")
    assert uv is not None
    result = subprocess.run(
        [uv, "run", "--script", str(LAUNCHER), "doctor"], cwd=cwd, env=env,
        text=True, capture_output=True,
    )

    assert result.returncode != 0
    error = json.loads(result.stderr)
    assert error["status"] == "error"
    assert error["code"] == "DOCKER_UNAVAILABLE"
