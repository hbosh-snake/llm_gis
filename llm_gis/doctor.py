from __future__ import annotations

import os
from pathlib import Path

from llm_gis.common import run_command, utc_now


def doctor_report() -> dict:
    gdal = run_command(["ogrinfo", "--version"]).strip()
    psql = run_command(["psql", "--version"]).strip()
    db_ok = False
    db_error = None
    try:
        run_command(["psql", "-v", "ON_ERROR_STOP=1", "-c", "SELECT 1;"])
        db_ok = True
    except Exception as exc:
        db_error = str(exc)

    paths = {
        "incoming_exists": Path("/data/incoming").exists(),
        "outgoing_exists": Path("/data/outgoing").exists(),
        "work_exists": Path("/data/work").exists(),
    }

    return {
        "created_at": utc_now(),
        "versions": {"gdal": gdal, "psql": psql},
        "database_ok": db_ok,
        "database_error": db_error,
        "paths": paths,
        "pg_env": {
            "PGHOST": os.getenv("PGHOST"),
            "PGPORT": os.getenv("PGPORT"),
            "PGDATABASE": os.getenv("PGDATABASE"),
            "PGUSER": os.getenv("PGUSER"),
        },
    }
