from __future__ import annotations

import os
from pathlib import Path

from llm_gis.common import incoming_root, run_command, utc_now, work_root
from llm_gis.errors import GisError


def doctor_report() -> dict:
    gdal = run_command(["ogrinfo", "--version"]).strip()
    psql = run_command(["psql", "--version"]).strip()
    db_ok = False
    db_error = None
    try:
        run_command(["psql", "-v", "ON_ERROR_STOP=1", "-c", "SELECT 1;"])
        db_ok = True
    except GisError as exc:
        db_error = exc.details.get("stderr", "").strip() or exc.message

    paths = {
        "incoming_exists": incoming_root().exists(),
        "outgoing_exists": Path("/data/outgoing").exists(),
        "work_exists": work_root().exists(),
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
