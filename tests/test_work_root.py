"""The workspace roots must be overridable, or nothing below stage can be tested offline."""

from pathlib import Path

from llm_gis.stage import stage_input

FIXTURES = Path(__file__).parent / "fixtures"


def test_stage_honours_the_overridden_roots(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "aoi.gpkg"
    source.write_bytes((FIXTURES / "aoi.gpkg").read_bytes())

    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(incoming))
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path / "work"))

    report = stage_input(source)

    assert report["staged_item"].startswith(str(tmp_path / "work"))
    assert Path(report["staged_item"]).exists()
    assert (tmp_path / "work" / "reports" / f"{report['ingest_id']}.json").exists()
    assert not Path("/data/work/staging").joinpath(report["ingest_id"]).exists()
