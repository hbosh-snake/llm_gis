from __future__ import annotations

from llm_gis.common import db_connect, utc_now


def list_ingestions(limit: int = 50) -> dict:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ingest_id, input_path, detected_crs, chosen_crs, status,
                       created_at, updated_at
                FROM meta.ingestions
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
    return {"ingestions": rows, "count": len(rows), "queried_at": utc_now()}
