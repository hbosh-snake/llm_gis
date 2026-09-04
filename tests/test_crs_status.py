import pytest
from pyproj import CRS

from llm_gis.common import crs_status, parse_epsg

LATLON_EXTENT = {"minx": 10.0, "miny": 45.0, "maxx": 10.3, "maxy": 45.3}
METRE_EXTENT = {"minx": 400000.0, "miny": 4990000.0, "maxx": 410000.0, "maxy": 5000000.0}

WGS84_WKT = CRS.from_epsg(4326).to_wkt()

CASES = [
    pytest.param(None, LATLON_EXTENT, "missing", id="no-crs"),
    pytest.param("EPSG:4326", LATLON_EXTENT, "ok", id="4326-latlon-extent"),
    pytest.param("EPSG:4326", METRE_EXTENT, "suspicious", id="4326-metre-extent"),
    pytest.param("EPSG:32632", LATLON_EXTENT, "suspicious", id="32632-latlon-extent"),
    pytest.param("EPSG:32632", METRE_EXTENT, "ok", id="32632-metre-extent"),
    pytest.param("EPSG:32632", None, "ok", id="no-extent"),
    # A geographic CRS given as WKT: its ellipsoid carries LENGTHUNIT["metre",1],
    # which a substring search mistakes for a projected CRS.
    pytest.param(WGS84_WKT, LATLON_EXTENT, "ok", id="4326-wkt-latlon-extent"),
    pytest.param(WGS84_WKT, METRE_EXTENT, "suspicious", id="4326-wkt-metre-extent"),
    pytest.param("not a crs at all", LATLON_EXTENT, "suspicious", id="unparseable"),
]


@pytest.mark.parametrize("crs_text,extent,expected_status", CASES)
def test_crs_status(crs_text, extent, expected_status):
    status, reasons = crs_status(crs_text, extent)
    assert status == expected_status
    if expected_status == "missing":
        assert reasons == ["No CRS detected"]
    elif expected_status == "suspicious":
        assert reasons


def test_parse_epsg_reads_wkt_not_just_epsg_strings():
    """raster2pgsql needs an SRID; raster CRS arrives as WKT, never as EPSG:nnnn."""
    assert parse_epsg("EPSG:32632") == 32632
    assert parse_epsg(WGS84_WKT) == 4326
    assert parse_epsg(None) is None
    assert parse_epsg("not a crs at all") is None
