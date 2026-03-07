# Agent Usability Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close four gaps that would cause a coder agent to stumble: missing schema/table introspection, missing ingestion listing, undocumented `analysis_<id>` schema creation requirement, and missing workflow walkthrough in LLM docs.

**Architecture:** Two new CLI commands (`list-ingestions`, `describe-table`) follow the existing pattern — a module in `llm_gis/`, a `@app.command` in `cli.py`, and a thin `bin/` wrapper. Documentation updates go to `docs/llm/README.md` and `docs/llm/manifest.json`.

**Tech Stack:** Python 3.12, psycopg3, typer, Docker Compose — same as existing codebase.

---

## Task 1: Add `list-ingestions` command

**Files:**
- Create: `llm_gis/list_ingestions.py`
- Modify: `llm_gis/cli.py`
- Create: `bin/list-ingestions`

**Step 1: Create the module**

Create `llm_gis/list_ingestions.py`:

```python
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
```

**Step 2: Wire into CLI**

In `llm_gis/cli.py`, add import at top:
```python
from llm_gis.list_ingestions import list_ingestions
```

Add command before `def main()`:
```python
@app.command("list-ingestions")
def list_ingestions_cmd(
    limit: int = typer.Option(50, help="Maximum rows to return"),
) -> None:
    typer.echo(json.dumps(list_ingestions(limit=limit), indent=2, sort_keys=True))
```

**Step 3: Create bin wrapper**

Create `bin/list-ingestions`:
```bash
#!/usr/bin/env bash
set -euo pipefail
docker compose run --rm agent uv run llm-gis list-ingestions "$@"
```

Make executable:
```bash
chmod +x bin/list-ingestions
```

**Step 4: Verify**

```bash
bin/list-ingestions
```

Expected: JSON with `{"ingestions": [...], "count": N, "queried_at": "..."}`. If DB is empty, `ingestions` is `[]` and `count` is `0`.

```bash
bin/list-ingestions --limit 5
```

Expected: at most 5 rows, sorted newest first.

**Step 5: Commit**

```bash
git add llm_gis/list_ingestions.py llm_gis/cli.py bin/list-ingestions
git commit -m "feat: add list-ingestions command"
```

---

## Task 2: Add `describe-table` command

**Files:**
- Create: `llm_gis/describe.py`
- Modify: `llm_gis/cli.py`
- Create: `bin/describe-table`

**Step 1: Create the module**

Create `llm_gis/describe.py`:

```python
from __future__ import annotations

from psycopg import sql

from llm_gis.common import db_connect, utc_now


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

            row_count: int | None = None
            if columns:
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
```

**Step 2: Wire into CLI**

In `llm_gis/cli.py`, add import at top:
```python
from llm_gis.describe import describe_table
```

Add command before `def main()`:
```python
@app.command("describe-table")
def describe_table_cmd(
    table_ref: str = typer.Argument(..., help="Fully qualified table: schema.table"),
) -> None:
    """Show columns and row count for a PostGIS table."""
    if "." not in table_ref:
        raise typer.BadParameter("table_ref must be schema.table, e.g. raw_<ingest_id>.roads")
    schema, table = table_ref.split(".", 1)
    typer.echo(json.dumps(describe_table(schema, table), indent=2, sort_keys=True))
```

**Step 3: Create bin wrapper**

Create `bin/describe-table`:
```bash
#!/usr/bin/env bash
set -euo pipefail
docker compose run --rm agent uv run llm-gis describe-table "$@"
```

Make executable:
```bash
chmod +x bin/describe-table
```

**Step 4: Verify**

First ingest a dataset if `raw_<ingest_id>.sometable` exists, or use any known table:

```bash
bin/describe-table meta.ingestions
```

Expected: JSON listing columns (`ingest_id`, `input_path`, `detected_crs`, etc.) with their types and `row_count`.

Test with a raw ingest table (substitute a real ingest_id):
```bash
bin/describe-table raw_<ingest_id>.aoi
```

Expected: columns include `fid`, `geom` (type `USER-DEFINED`), and all source attribute columns in lowercase.

Test bad input:
```bash
bin/describe-table notqualified
```

Expected: error `table_ref must be schema.table`.

**Step 5: Commit**

```bash
git add llm_gis/describe.py llm_gis/cli.py bin/describe-table
git commit -m "feat: add describe-table command"
```

---

## Task 3: Update LLM documentation

**Files:**
- Modify: `docs/llm/README.md`
- Modify: `docs/llm/manifest.json`

**Step 1: Update README.md**

Replace the full content of `docs/llm/README.md` with the following (add new sections; keep existing content):

Add under `## Commands`, after the `bin/doctor` entry, the two new commands:

```markdown
### `bin/list-ingestions`
Query `meta.ingestions` and return all ingests sorted newest-first.
```
bin/list-ingestions [--limit 50]
```
Output fields: `ingest_id`, `input_path`, `detected_crs`, `chosen_crs`, `status`, `created_at`, `updated_at`.

### `bin/describe-table`
Return column names, types, and row count for any PostGIS table.
```
bin/describe-table <schema.table>
```
Examples: `bin/describe-table meta.ingestions`, `bin/describe-table raw_<ingest_id>.roads`.
Output fields: `schema`, `table`, `columns` (list of `{column_name, data_type, is_nullable}`), `row_count`.
```

Add a new section `## Known behaviors` before `## CRS policy`:

```markdown
## Known behaviors

### Column names are always lowercase
`ogr2ogr` lowercases all attribute column names when loading to PostgreSQL. A source field `Name` becomes `name`, `OBJECTID` becomes `objectid`. Always use lowercase in SQL.

### Geometry column is always `geom`, FID is `fid`
Every vector table loaded by `ingest-vector` uses `-lco GEOMETRY_NAME=geom -lco FID=fid`. Reference geometry as `geom` in all SQL.

### `analysis_<ingest_id>` schema must be created by your SQL
`run-sql` sets `search_path` but does NOT create the analysis schema. Your SQL file must start with:
```sql
CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;
```
Replace `<ingest_id>` with the literal value returned by `ingest-vector`.
```

Add a new section `## Standard workflow` at the end:

```markdown
## Standard workflow

A complete workflow from raw data to export. Each command outputs JSON; the key fields needed for the next step are shown explicitly.

**1. Inspect the dataset**
```
bin/inspect /data/incoming/mydata.gpkg
```
Check `crs_status` in the output:
- `"ok"` → proceed
- `"missing"` or `"suspicious"` → add `--src-crs EPSG:XXXX` to the ingest command

**2. Ingest**
```
bin/ingest-vector /data/incoming/mydata.gpkg --table roads --dst-crs EPSG:3035
```
From the JSON output, note the `ingest_id` value (e.g. `"20260307120000_abc123def4"`). You will use this in every subsequent step.

The raw table is now at `raw_<ingest_id>.roads`. All column names are lowercase.

**3. Describe the raw table (discover column names)**
```
bin/describe-table raw_<ingest_id>.roads
```
Use the returned `columns` list to write correct SQL.

**4. Write and run analysis SQL**

Create `/workspace/data/work/analysis_<ingest_id>.sql`:
```sql
CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;

CREATE TABLE analysis_<ingest_id>.roads_buffer AS
SELECT fid, name, ST_Buffer(geom, 100) AS geom
FROM roads;
```

Then run it:
```
bin/run-sql /workspace/data/work/analysis_<ingest_id>.sql --ingest-id <ingest_id>
```

**5. Describe the result (verify it was created)**
```
bin/describe-table analysis_<ingest_id>.roads_buffer
```

**6. Export**
```
bin/export /data/outgoing/roads_buffer.gpkg --format gpkg --table analysis_<ingest_id>.roads_buffer
bin/export /data/outgoing/roads_buffer.geojson --format geojson --table analysis_<ingest_id>.roads_buffer
```

**7. List all ingestions (to review or resume work)**
```
bin/list-ingestions
```
```

**Step 2: Update manifest.json**

Add the two new commands to the `"commands"` array in `docs/llm/manifest.json`:

```json
{
  "name": "list-ingestions",
  "entrypoint": "bin/list-ingestions",
  "description": "List all ingestions from meta.ingestions, newest first.",
  "args": [
    {"name": "--limit", "required": false, "default": 50, "description": "Max rows to return"}
  ],
  "example": "bin/list-ingestions --limit 10"
},
{
  "name": "describe-table",
  "entrypoint": "bin/describe-table",
  "description": "Return column names, types, and row count for a PostGIS table.",
  "args": [
    {"name": "table_ref", "required": true, "description": "Fully qualified: schema.table"}
  ],
  "example": "bin/describe-table raw_20260307120000_abc123def4.roads"
}
```

Also add a `"known_behaviors"` key to the manifest at the top level:

```json
"known_behaviors": {
  "column_names_lowercased": "ogr2ogr lowercases all attribute column names on ingest. Source field 'Name' becomes 'name'.",
  "geometry_column": "geom",
  "fid_column": "fid",
  "analysis_schema_not_auto_created": "run-sql sets search_path but does not CREATE SCHEMA. Your SQL must include: CREATE SCHEMA IF NOT EXISTS analysis_<ingest_id>;"
}
```

**Step 3: Verify**

```bash
# Validate manifest is valid JSON
docker compose run --rm agent bash -c "jq . /workspace/docs/llm/manifest.json"
```

Expected: no errors, all new fields present.

**Step 4: Commit**

```bash
git add docs/llm/README.md docs/llm/manifest.json
git commit -m "docs: add workflow guide, known behaviors, new commands to LLM docs"
```

---

## Final check

Run `bin/doctor` to confirm the environment is healthy, then run the full workflow from the new README to smoke-test the new commands end-to-end:

```bash
bin/doctor
bin/list-ingestions
# If any ingest_id is available:
bin/describe-table meta.ingestions
```

Expected: all commands return valid JSON, no errors.
