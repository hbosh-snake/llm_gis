"""An alias or a URL, and nothing in between."""

from __future__ import annotations

import pytest

from llm_gis.catalog import CATALOGS, resolve_endpoint
from llm_gis.errors import GisError


def test_a_known_alias_resolves_to_its_url():
    assert resolve_endpoint("overture") == "https://stac.overturemaps.org/catalog.json"


def test_every_alias_is_an_https_url():
    for name, url in CATALOGS.items():
        assert url.startswith("https://"), name


def test_a_url_passes_through_unchanged():
    url = "https://example.invalid/stac/v1/"
    assert resolve_endpoint(url) == url


def test_an_unknown_bare_name_is_a_gis_error_naming_the_known_ones():
    with pytest.raises(GisError) as caught:
        resolve_endpoint("nosuchcatalogue")
    assert caught.value.code == "INPUT_NOT_FOUND"
    assert "overture" in caught.value.suggested_action
