"""Framing is pure and asserted directly; rendering is asserted on the files it writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_gis import preview

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def work_root(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_GIS_WORK_ROOT", str(tmp_path))


def test_the_frame_is_the_union_of_dataset_and_aoi():
    frame = preview.frame(
        {"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0},
        {"minx": 5.0, "miny": 5.0, "maxx": 6.0, "maxy": 6.0},
    )

    assert frame["bbox_4326"]["minx"] <= 0.0
    assert frame["bbox_4326"]["maxx"] >= 6.0
    assert frame["size"] == [512, 512]


def test_the_frame_without_an_aoi_is_the_dataset_alone():
    frame = preview.frame({"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0}, None)

    assert frame["bbox_4326"]["maxx"] < 2.0


def test_the_frame_is_padded_and_never_zero_sized():
    """A point dataset has no width; a frame with no width cannot be rendered."""
    frame = preview.frame({"minx": 9.0, "miny": 45.0, "maxx": 9.0, "maxy": 45.0}, None)

    box = frame["bbox_4326"]
    assert box["maxx"] > box["minx"]
    assert box["maxy"] > box["miny"]


def test_rendering_a_raster_writes_a_png_and_a_sidecar(tmp_path):
    result = preview.render(str(FIXTURES / "scene.tif"), output=str(tmp_path / "scene"))

    png = Path(result["png"])
    sidecar = json.loads(Path(result["sidecar"]).read_text())

    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert sidecar["render"]["channels"] == {"r": "data", "g": "aoi", "b": "graticule"}
    assert sidecar["render"]["scale"]["min"] is not None
    assert sidecar["summary"]["aoi_intersects"] is None


def test_rendering_a_vector_writes_a_png(tmp_path):
    result = preview.render(str(FIXTURES / "aoi.gpkg"), output=str(tmp_path / "aoi"))

    assert Path(result["png"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert result["kind"] == "vector"


def test_output_directory_holds_only_the_png_and_sidecar(tmp_path):
    outgoing = tmp_path / "outgoing"
    preview.render(str(FIXTURES / "scene.tif"), output=str(outgoing / "scene"))

    produced = {p.name for p in outgoing.iterdir()}
    assert produced == {"scene.png", "scene.preview.json"}


def test_a_disjoint_aoi_is_reported_in_the_sidecar(tmp_path):
    """The number the picture is meant to show, so the two can be compared."""
    result = preview.render(
        str(FIXTURES / "scene.tif"),
        aoi=str(FIXTURES / "aoi.gpkg"),
        output=str(tmp_path / "disjoint"),
    )

    sidecar = json.loads(Path(result["sidecar"]).read_text())
    assert sidecar["summary"]["aoi_intersects"] is False


def test_the_render_is_deterministic(tmp_path):
    first = preview.render(str(FIXTURES / "scene.tif"), output=str(tmp_path / "a"))
    second = preview.render(str(FIXTURES / "scene.tif"), output=str(tmp_path / "b"))

    assert Path(first["png"]).read_bytes() == Path(second["png"]).read_bytes()
