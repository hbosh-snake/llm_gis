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


PARQUET_MEDIA_TYPES = {
    "application/vnd.apache.parquet",
    "application/x-parquet",
    "application/parquet",
}

ADVERTISED_PROPERTIES = ("num_rows", "eo:cloud_cover", "proj:epsg")


def readable_by(media_type: str | None) -> list[str]:
    """Which engine can open this media type. A format fact, not a routing decision.

    Phase 6's planner subsumes this. It must not grow a second opinion here.
    """
    return ["duckdb"] if media_type in PARQUET_MEDIA_TYPES else []


def _self_href(document: dict) -> str | None:
    for link in document.get("links") or []:
        if link.get("rel") == "self":
            return link.get("href")
    return None


def flatten_item(item: dict) -> dict:
    """A STAC item as a flat dict. Properties pass through verbatim."""
    properties = item.get("properties") or {}
    return {
        "id": item.get("id"),
        "collection": item.get("collection"),
        "self": _self_href(item),
        "bbox": item.get("bbox"),
        "datetime": properties.get("datetime"),
        "properties": properties,
        "asset_count": len(item.get("assets") or {}),
    }


def flatten_asset(key: str, asset: dict, properties: dict) -> dict:
    """One asset, with the publisher's claims quarantined under 'advertised'."""
    advertised = {"size_bytes": asset.get("file:size")}
    for name in ADVERTISED_PROPERTIES:
        if name in properties:
            advertised[name] = properties[name]
    return {
        "key": key,
        "href": asset.get("href"),
        "media_type": asset.get("type"),
        "roles": asset.get("roles") or [],
        "advertised": advertised,
        "readable_by": readable_by(asset.get("type")),
    }


def flatten_collection(collection: dict) -> dict:
    """A STAC collection, keeping the per-item sub-extents traversal prefilters on."""
    bboxes = ((collection.get("extent") or {}).get("spatial") or {}).get("bbox") or []
    return {
        "id": collection.get("id"),
        "title": collection.get("title"),
        "description": collection.get("description"),
        "license": collection.get("license"),
        "self": _self_href(collection),
        "bbox": bboxes[0] if bboxes else None,
        "sub_extents": list(bboxes[1:]),
    }
