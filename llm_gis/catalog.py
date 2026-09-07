"""STAC discovery: what is out there, and what can read it.

Never downloads an asset. The output is hrefs plus the metadata the
publisher advertises, so a caller can decide what is worth opening.
"""

from __future__ import annotations

from llm_gis.errors import INPUT_NOT_FOUND, GisError

CATALOGS = {
    "overture": "https://stac.overturemaps.org/catalog.json",
    "cdse": "https://stac.dataspace.copernicus.eu/v1/",
    "earth-search": "https://earth-search.aws.element84.com/v1/",
}


def resolve_endpoint(catalog: str) -> str:
    """An alias from CATALOGS, or any URL passed through unchanged."""
    if catalog.startswith(("http://", "https://")):
        return catalog
    if catalog in CATALOGS:
        return CATALOGS[catalog]
    raise GisError(
        INPUT_NOT_FOUND,
        f"No catalogue named {catalog}",
        f"Use a full https URL, or one of: {', '.join(sorted(CATALOGS))}",
    )
