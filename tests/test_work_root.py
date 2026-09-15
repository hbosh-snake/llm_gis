"""The workspace roots must be overridable, or nothing below stage can be tested offline."""

from pathlib import Path
import os

import pytest

from llm_gis.common import allowed_source_roots, ensure_source_path
from llm_gis.errors import PATH_OUTSIDE_ROOT, GisError
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


def test_allowed_source_roots_keep_legacy_incoming_root_by_default(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(incoming))
    monkeypatch.delenv("LLM_GIS_SOURCE_ROOTS", raising=False)

    assert allowed_source_roots() == (incoming.resolve(),)


def test_allowed_source_roots_include_two_os_pathsep_extra_roots(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    first = tmp_path / "first"
    second = tmp_path / "second"
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(incoming))
    monkeypatch.setenv("LLM_GIS_SOURCE_ROOTS", f"{first}{os.pathsep}{second}")

    assert allowed_source_roots() == (incoming.resolve(), first.resolve(), second.resolve())


def test_stage_accepts_source_from_extra_root_and_preserves_explicit_id(monkeypatch, tmp_path):
    incoming = tmp_path / "incoming"
    extra = tmp_path / "extra"
    extra.mkdir()
    source = extra / "source.txt"
    source.write_text("source", encoding="utf-8")
    work = tmp_path / "work"
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(incoming))
    monkeypatch.setenv("LLM_GIS_SOURCE_ROOTS", str(extra))
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(work))

    report = stage_input(source, ingest_id="kept-id")

    assert report["ingest_id"] == "kept-id"
    assert Path(report["staged_item"]).exists()


def test_ensure_source_path_accepts_resolved_containment(monkeypatch, tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    nested = root / "nested"
    nested.mkdir()
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(root))

    ensure_source_path(nested / ".." / "nested" / "source.gpkg")


def test_ensure_source_path_rejects_outside_path(monkeypatch, tmp_path):
    root = tmp_path / "sources"
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(root))

    with pytest.raises(GisError) as excinfo:
        ensure_source_path(tmp_path / "outside" / "source.gpkg")
    assert excinfo.value.code == PATH_OUTSIDE_ROOT


def test_allowed_source_roots_reject_filesystem_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_INCOMING_ROOT", str(tmp_path / "incoming"))
    monkeypatch.setenv("LLM_GIS_SOURCE_ROOTS", "/")

    with pytest.raises(GisError) as excinfo:
        allowed_source_roots()
    assert excinfo.value.code == PATH_OUTSIDE_ROOT
    assert "specific source directories" in excinfo.value.suggested_action
