from __future__ import annotations

from psycopg import sql

from llm_gis.common import db_connect, utc_now
from llm_gis.errors import TABLE_NOT_FOUND, GisError


def describe_table(schema: str, table: str) -> dict:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema, table),
            )
            cols = [desc[0] for desc in cur.description]
            columns = [dict(zip(cols, row)) for row in cur.fetchall()]

            if not columns:
                cur.execute("SELECT to_regclass(%s);", (f"{schema}.{table}",))
                exists = cur.fetchone()[0] is not None
                if exists:
                    raise GisError(
                        TABLE_NOT_FOUND,
                        f"Table {schema}.{table} exists but no columns are visible to this role",
                        "Grant SELECT on the table to the connecting role",
                    )
                raise GisError(
                    TABLE_NOT_FOUND,
                    f"Table {schema}.{table} does not exist",
                    "Run list-ingestions to see available schemas, or describe an existing table",
                )

            cur.execute(
                sql.SQL("SELECT COUNT(*) FROM {}.{};").format(
                    sql.Identifier(schema), sql.Identifier(table)
                )
            )
            row_count = int(cur.fetchone()[0])

    return {
        "schema": schema,
        "table": table,
        "columns": columns,
        "row_count": row_count,
        "queried_at": utc_now(),
    }
