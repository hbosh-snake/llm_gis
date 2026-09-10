"""The planner's rule table, asserted directly. Nothing here opens a file."""

from __future__ import annotations

import pytest

from llm_gis.errors import UNSUPPORTED_FORMAT, GisError
from llm_gis.planner import DUCKDB, NO_CONVERSION_PATH, POSTGIS, classify, route, steps


def test_a_local_geoparquet_is_parquet_and_duckdb_only():
    source = classify("/data/incoming/buildings.parquet")
    assert source.format == "parquet"
    assert source.locality == "local"
    assert source.readers == [DUCKDB]


def test_a_remote_href_is_remote():
    assert classify("https://example.com/a/b.parquet").locality == "remote"
    assert classify("s3://bucket/b.parquet").locality == "remote"


def test_a_query_string_does_not_hide_the_suffix():
    """A signed URL carries its token after the path; duck.reader_sql splits the same way."""
    assert classify("https://example.com/b.parquet?token=abc").format == "parquet"


def test_a_geopackage_is_readable_by_both_engines():
    """DuckDB reads it with ST_Read; ingest-vector loads it. Both routes are real."""
    source = classify("/data/incoming/aoi.gpkg")
    assert source.format == "vector_file"
    assert source.readers == [DUCKDB, POSTGIS]


def test_a_schema_qualified_name_is_a_postgis_table():
    source = classify("analysis_aoi.result")
    assert source.format == "postgis_table"
    assert source.readers == [POSTGIS]


def test_a_raster_has_no_reader_yet():
    """Phase 7 owns cloud raster. Saying so beats guessing a route."""
    source = classify("/data/incoming/dem.tif")
    assert source.format == "raster"
    assert source.readers == []


def test_an_unrecognised_suffix_is_an_error_not_a_guess():
    with pytest.raises(GisError) as caught:
        classify("/data/incoming/notes.docx")
    assert caught.value.code == UNSUPPORTED_FORMAT


def _route(operation, uri, **kwargs):
    return route(operation, classify(uri), **kwargs)


def test_a_remote_geoparquet_query_reads_in_place():
    result = _route("query", "https://example.com/buildings.parquet")
    assert result.strategy == DUCKDB
    assert result.fallback is None
    assert result.reason


def test_a_local_geopackage_query_prefers_duckdb_and_names_the_other_route():
    result = _route("query", "/data/incoming/aoi.gpkg")
    assert result.strategy == DUCKDB
    assert result.fallback["strategy"] == POSTGIS
    assert result.fallback["requires"]


def test_materialising_a_geopackage_query_goes_to_postgis():
    result = _route("query", "/data/incoming/aoi.gpkg", materialise=True)
    assert result.strategy == POSTGIS
    assert result.fallback["strategy"] == DUCKDB
    assert result.fallback["loses"] == "persistence"


def test_a_remote_vector_file_warns_about_the_read():
    result = _route("query", "https://example.com/aoi.gpkg")
    assert result.strategy == DUCKDB
    assert [w["code"] for w in result.warnings] == ["REMOTE_UNINDEXED_READ"]


def test_a_postgis_table_query_stays_in_postgis():
    assert _route("query", "analysis_aoi.result").strategy == POSTGIS


def test_analyse_always_uses_the_persistent_workspace():
    """Crossing sources in SQL is what the workspace is for; --materialise is moot."""
    assert _route("analyse", "/data/incoming/aoi.gpkg").strategy == POSTGIS
    assert _route("analyse", "/data/incoming/aoi.gpkg", materialise=False).strategy == POSTGIS


def test_exporting_a_file_never_enters_the_database():
    assert _route("export", "/data/incoming/buildings.parquet").strategy == DUCKDB
    assert _route("export", "analysis_aoi.result").strategy == POSTGIS


def test_materialising_a_parquet_source_is_blocked_with_the_reason():
    """GDAL here has no Parquet driver and duck-query writes Parquet. Say so."""
    result = _route("query", "/data/incoming/buildings.parquet", materialise=True)
    assert result.strategy is None
    assert result.blocked_by["code"] == NO_CONVERSION_PATH
    assert result.blocked_by["suggested_action"]


def test_analysing_a_parquet_source_is_blocked_the_same_way():
    result = _route("analyse", "https://example.com/buildings.parquet")
    assert result.strategy is None
    assert result.blocked_by["code"] == NO_CONVERSION_PATH


def test_a_raster_has_no_route_at_all():
    with pytest.raises(GisError) as caught:
        _route("query", "/data/incoming/dem.tif")
    assert caught.value.code == UNSUPPORTED_FORMAT


def test_an_engine_override_beats_the_rules_and_says_so():
    result = _route("query", "/data/incoming/aoi.gpkg", engine=POSTGIS)
    assert result.strategy == POSTGIS
    assert result.overridden == "engine"


def test_an_override_the_source_cannot_honour_is_refused():
    """An override is someone saying they know better; routing around them silently
    destroys the only signal that they were wrong."""
    with pytest.raises(GisError) as caught:
        _route("query", "analysis_aoi.result", engine=DUCKDB)
    assert caught.value.code == UNSUPPORTED_FORMAT
    assert caught.value.details["requested_engine"] == DUCKDB


def test_forcing_postgis_onto_parquet_reports_the_gap_rather_than_refusing():
    """An override cannot conjure a route that does not exist. Name the prerequisite."""
    result = _route("query", "https://example.com/b.parquet", engine=POSTGIS)
    assert result.strategy is None
    assert result.blocked_by["code"] == NO_CONVERSION_PATH


def test_a_duckdb_query_is_one_step_carrying_the_real_arguments():
    source = classify("/data/incoming/aoi.gpkg")
    decided = route("query", source)
    plan = steps("query", source, decided, bbox="8.5,45.0,9.5,45.6", where="kind = 'wood'",
                 output="/data/outgoing/2026-09-10_aoi/matches.parquet")
    assert [s.command for s in plan] == ["duck-query"]
    assert plan[0].argv == [
        "/data/incoming/aoi.gpkg",
        "--bbox", "8.5,45.0,9.5,45.6",
        "--where", "kind = 'wood'",
        "--output", "/data/outgoing/2026-09-10_aoi/matches.parquet",
    ]


def test_omitted_arguments_leave_no_empty_flags():
    source = classify("https://example.com/b.parquet")
    plan = steps("query", source, route("query", source))
    assert plan[0].argv == ["https://example.com/b.parquet"]


def test_a_materialised_query_stages_ingests_and_exports():
    source = classify("/data/incoming/aoi.gpkg")
    decided = route("query", source, materialise=True)
    plan = steps("query", source, decided, bbox="8.5,45.0,9.5,45.6",
                 output="/data/outgoing/2026-09-10_aoi/result.gpkg")
    assert [s.command for s in plan] == ["stage", "ingest-vector", "export"]
    assert plan[0].argv == ["/data/incoming/aoi.gpkg", "--ingest-id", "aoi"]
    assert plan[1].argv == [
        "/data/work/staging/aoi/aoi.gpkg", "--table", "aoi", "--ingest-id", "aoi",
    ]
    assert plan[2].argv[0] == "/data/outgoing/2026-09-10_aoi/result.gpkg"
    assert "ST_MakeEnvelope(8.5,45.0,9.5,45.6, ST_SRID(geom))" in plan[2].argv[-1]


def test_the_ingest_id_is_derived_so_every_step_pastes_without_editing():
    """stage picks a timestamped id unless told one; the plan tells it one."""
    source = classify("/data/incoming/Milano AOI.gpkg")
    plan = steps("query", source, route("query", source, materialise=True))
    assert plan[0].argv[2] == "milano_aoi"


def test_an_analyse_plan_runs_sql_between_ingest_and_export():
    source = classify("/data/incoming/aoi.gpkg")
    decided = route("analyse", source)
    plan = steps("analyse", source, decided, sql_path="/data/work/sql/overlay.sql",
                 output="/data/outgoing/2026-09-10_aoi/result.gpkg")
    assert [s.command for s in plan] == ["stage", "ingest-vector", "run-sql", "export"]
    assert plan[2].argv == ["/data/work/sql/overlay.sql", "--ingest-id", "aoi"]


def test_a_blocked_route_produces_no_steps():
    source = classify("/data/incoming/buildings.parquet")
    decided = route("query", source, materialise=True)
    assert steps("query", source, decided) == []


def test_every_step_explains_itself():
    source = classify("/data/incoming/aoi.gpkg")
    plan = steps("query", source, route("query", source, materialise=True))
    assert all(s.why for s in plan)
