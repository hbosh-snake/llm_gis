"""QC over a real PostGIS table. Requires the compose stack: bin/test -m live."""

from __future__ import annotations

import shutil
from pathlib import Path

import psycopg
import pytest

from llm_gis.common import db_connect, sanitize_identifier
from llm_gis.ingest_vector import ingest_vector
from llm_gis.qc import QcContext, qc_report

FIXTURES = Path(__file__).parent.parent / "fixtures"
TABLE_NAME = "aoi_qc"


@pytest.fixture
def ingested(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(incoming))
    source = incoming / "aoi.gpkg"
    shutil.copy2(FIXTURES / "aoi.gpkg", source)

    report = ingest_vector(
        input_path=source, table=TABLE_NAME, ingest_id=None,
        src_crs=None, dst_crs=None, schema=None,
    )
    yield report["schema"], TABLE_NAME

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                psycopg.sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE;").format(
                    psycopg.sql.Identifier(report["schema"])
                )
            )


@pytest.mark.live
def test_qc_over_a_postgis_table(ingested):
    schema, table = ingested
    report = qc_report(f"{schema}.{table}", QcContext())
    metrics = report["metrics"]
    assert report["source"]["kind"] == "postgis_table"
    assert metrics["vector"]["feature_count"] == 4
    assert metrics["vector"]["invalid_count"] == 0
    assert metrics["crs"] == "EPSG:4326"
    assert metrics["bbox"]["minx"] == pytest.approx(10.0)
    assert metrics["vector"]["duplicate_id_count"] == 0


@pytest.mark.live
def test_a_metric_operation_on_a_geographic_table_warns(ingested):
    schema, table = ingested
    report = qc_report(f"{schema}.{table}", QcContext(metric_op=True))
    assert "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION" in [w["code"] for w in report["warnings"]]


@pytest.mark.live
def test_a_missing_table_is_a_gis_error():
    from llm_gis.errors import TABLE_NOT_FOUND, GisError

    with pytest.raises(GisError) as caught:
        qc_report("raw_nope.nothing", QcContext())
    assert caught.value.code == TABLE_NOT_FOUND
