from __future__ import annotations

import os
from pathlib import Path

from llm_gis.common import ensure_workspace_dirs, run_command, sanitize_identifier, utc_now
from llm_gis.errors import INPUT_NOT_FOUND, GisError


WORK_ROOT = Path("/data/work")


def run_sql_file(sql_path: Path, ingest_id: str, statement_timeout: str = "5min") -> dict:
    ensure_workspace_dirs()
    if not sql_path.exists():
        raise GisError(
            INPUT_NOT_FOUND,
            f"SQL file does not exist: {sql_path}",
            "Check the path; SQL files are read from inside the container, usually under /data/work",
        )

    sid = sanitize_identifier(ingest_id)
    sql_text = sql_path.read_text(encoding="utf-8")
    preamble = (
        f"SET statement_timeout = '{statement_timeout}';\n"
        f"SET search_path TO analysis_{sid},raw_{sid},public;\n"
    )
    combined = preamble + "\n" + sql_text

    log_dir = WORK_ROOT / "logs" / sid
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "run-sql.log"

    output = run_command(["psql", "-v", "ON_ERROR_STOP=1", "-f", "-"], input_text=combined, env=os.environ.copy())
    log_file.write_text(output, encoding="utf-8")

    return {
        "ingest_id": sid,
        "sql_path": str(sql_path),
        "log_file": str(log_file),
        "executed_at": utc_now(),
    }
