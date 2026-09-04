import pytest

from llm_gis.common import crs_status

LATLON_EXTENT = {"minx": 10.0, "miny": 45.0, "maxx": 10.3, "maxy": 45.3}
METRE_EXTENT = {"minx": 400000.0, "miny": 4990000.0, "maxx": 410000.0, "maxy": 5000000.0}

CASES = [
    pytest.param(None, LATLON_EXTENT, "missing", id="no-crs"),
    pytest.param("EPSG:4326", LATLON_EXTENT, "ok", id="4326-latlon-extent"),
    pytest.param("EPSG:4326", METRE_EXTENT, "suspicious", id="4326-metre-extent"),
    pytest.param("EPSG:32632", LATLON_EXTENT, "suspicious", id="32632-latlon-extent"),
    pytest.param("EPSG:32632", METRE_EXTENT, "ok", id="32632-metre-extent"),
    pytest.param("EPSG:32632", None, "ok", id="no-extent"),
]


@pytest.mark.parametrize("crs_text,extent,expected_status", CASES)
def test_crs_status(crs_text, extent, expected_status):
    status, reasons = crs_status(crs_text, extent)
    assert status == expected_status
    if expected_status == "missing":
        assert reasons == ["No CRS detected"]
    elif expected_status == "suspicious":
        assert reasons
