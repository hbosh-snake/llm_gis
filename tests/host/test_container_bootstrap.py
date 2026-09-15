"""The agent container must start its Python without downloading anything."""

import os
from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[2]


def compose_run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"LLM_GIS_UID": str(os.getuid()), "LLM_GIS_GID": str(os.getgid())}
    return subprocess.run(
        ["docker", "compose", "--progress", "quiet", "-f", str(REPO / "docker-compose.yml"),
         "--project-directory", str(REPO), "run", "--rm", *args],
        env=env, text=True, capture_output=True,
    )


@pytest.mark.live
def test_uv_python_lives_on_a_persistent_volume():
    """uv's managed Python under ephemeral HOME=/tmp was re-downloaded on every call."""
    result = compose_run("agent", "printenv", "UV_PYTHON_INSTALL_DIR")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("/opt/llm-gis/cache/")


@pytest.mark.live
def test_backend_runs_offline():
    result = compose_run("-e", "UV_OFFLINE=1", "agent",
                         "uv", "run", "--project", "/workspace", "--quiet", "llm-gis", "doctor")
    assert result.returncode == 0, result.stderr
