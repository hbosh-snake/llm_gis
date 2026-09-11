"""The one place the VSI convention is stated. Pure; no GDAL runs here."""

from __future__ import annotations

import pytest

from llm_gis.common import GisError, gdal_uri, is_remote, remote_read_error


def test_an_https_url_becomes_a_vsicurl_path():
    assert gdal_uri("https://example.com/b.tif") == "/vsicurl/https://example.com/b.tif"


def test_an_http_url_becomes_a_vsicurl_path():
    assert gdal_uri("http://example.com/b.tif") == "/vsicurl/http://example.com/b.tif"


def test_an_s3_url_becomes_a_vsis3_path():
    """The scheme is dropped: /vsis3/ takes bucket/key, not the s3:// form."""
    assert gdal_uri("s3://bucket/key/b.tif") == "/vsis3/bucket/key/b.tif"


def test_a_local_path_passes_through_unchanged():
    assert gdal_uri("/data/incoming/elevation.tif") == "/data/incoming/elevation.tif"


def test_a_query_string_survives():
    """A signed URL carries its token after the path and GDAL needs all of it."""
    assert gdal_uri("https://e.com/b.tif?sig=x") == "/vsicurl/https://e.com/b.tif?sig=x"


def test_locality():
    assert is_remote("https://example.com/b.tif")
    assert is_remote("s3://bucket/b.tif")
    assert not is_remote("/data/incoming/b.tif")


def test_a_remote_failure_names_itself_and_carries_the_status():
    inner = GisError(
        "COMMAND_FAILED",
        "Command failed with exit 1: gdalinfo -json /vsicurl/https://e.com/b.tif",
        "Read details.stderr for the underlying tool diagnostic",
        {"stderr": "ERROR 11: HTTP response code: 403"},
    )

    with pytest.raises(GisError) as error:
        raise remote_read_error("https://e.com/b.tif", inner)

    assert error.value.code == "REMOTE_READ_FAILED"
    assert error.value.details["http_status"] == 403
    assert error.value.details["uri"] == "https://e.com/b.tif"


def test_a_remote_failure_with_no_status_still_reports_the_uri():
    inner = GisError("COMMAND_FAILED", "boom", "look at stderr", {"stderr": "ERROR 4: no such file"})

    raised = remote_read_error("https://e.com/b.tif", inner)

    assert raised.details["http_status"] is None
