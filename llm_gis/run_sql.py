from __future__ import annotations

import os
from pathlib import Path

from psycopg import sql

from llm_gis.common import db_connect, ensure_workspace_dirs, run_command, sanitize_identifier, utc_now
from llm_gis.errors import INPUT_NOT_FOUND, GisError


WORK_ROOT = Path("/data/work")


def _analysis_tables(schema: str) -> list[dict]:
    """Tables in the run's analysis schema after execution, each with its row count."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name;",
                (schema,),
            )
            names = [row[0] for row in cur.fetchall()]
            tables = []
            for name in names:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) FROM {}.{};").format(sql.Identifier(schema), sql.Identifier(name))
                )
                tables.append({"table": name, "row_count": int(cur.fetchone()[0])})
    return tables


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

    analysis_schema = f"analysis_{sid}"
    return {
        "ingest_id": sid,
        "sql_path": str(sql_path),
        "log_file": str(log_file),
        "schema": analysis_schema,
        "tables": _analysis_tables(analysis_schema),
        "executed_at": utc_now(),
    }
