"""STAC discovery: what is out there, and what can read it.

Never downloads an asset. The output is hrefs plus the metadata the
publisher advertises, so a caller can decide what is worth opening.
"""

from __future__ import annotations

from llm_gis import stac_fetch
from llm_gis.asset import STAC_ASSET, Asset, Provenance
from llm_gis.errors import CATALOG_MALFORMED, INPUT_NOT_FOUND, GisError
from llm_gis.planner import DUCKDB, classify

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
    """Whether duck-query can consume this href directly. A compatibility surface.

    Phase 6 subsumed the routing table this once held: `planner.readers` is now the
    single authoritative one, and this is a projection of it. The returned values are
    unchanged, and deliberately narrower than `readers`: a GeoPackage over HTTP can be
    opened by DuckDB, but not by the Parquet query path this field describes.
    """
    return [DUCKDB] if media_type in PARQUET_MEDIA_TYPES else []


def readers_for(href: str | None) -> list[str]:
    """What could open this href at all, per the planner. Never raises on a stray asset."""
    if not href:
        return []
    try:
        return classify(href).readers
    except GisError:
        return []


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


def build_asset(
    key: str,
    asset: dict,
    properties: dict,
    *,
    item_url: str | None = None,
    item_id: str | None = None,
) -> Asset:
    """One STAC asset as an Asset, with the publisher's claims left under `advertised`.

    Nothing here is measured: no asset bytes are fetched, so `crs`, `bbox` and
    `record_count` stay None however much the publisher advertises.
    """
    advertised = {"size_bytes": asset.get("file:size")}
    for name in ADVERTISED_PROPERTIES:
        if name in properties:
            advertised[name] = properties[name]
    return Asset(
        uri=asset.get("href"),
        provenance=Provenance(
            STAC_ASSET, catalog_url=item_url, item_id=item_id, asset_key=key
        ),
        media_type=asset.get("type"),
        roles=asset.get("roles") or [],
        readable_by=readable_by(asset.get("type")),
        readers=readers_for(asset.get("href")),
        advertised=advertised,
    )


def _to_asset_json(asset: Asset) -> dict:
    """The historic per-asset keys, unchanged."""
    return {
        "key": asset.provenance.asset_key,
        "href": asset.uri,
        "media_type": asset.media_type,
        "roles": asset.roles,
        "advertised": asset.advertised,
        "readable_by": asset.readable_by,
        "readers": asset.readers,
    }


def flatten_asset(
    key: str,
    asset: dict,
    properties: dict,
    *,
    item_url: str | None = None,
    item_id: str | None = None,
) -> dict:
    """One asset, with the publisher's claims quarantined under 'advertised'."""
    return _to_asset_json(
        build_asset(key, asset, properties, item_url=item_url, item_id=item_id)
    )


def _item_count(collection: dict) -> int:
    return sum(1 for link in collection.get("links") or [] if link.get("rel") == "item")


def _union_bbox(boxes: list[list[float]]) -> list[float]:
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def flatten_collection(collection: dict) -> dict:
    """A STAC collection, keeping the per-item sub-extents traversal prefilters on.

    STAC's documented convention is an overall extent at index 0 followed by
    one sub-extent per item. Overture's live catalogues instead list exactly
    one bbox per item with no leading overall entry; reporting bboxes[0] as
    "the" collection extent there would mislead, since it is really just the
    first item's own narrow bbox. The item count settles which shape a given
    document actually uses, and the overall extent is computed when absent.
    """
    bboxes = ((collection.get("extent") or {}).get("spatial") or {}).get("bbox") or []
    item_count = _item_count(collection)
    if item_count and len(bboxes) == item_count:
        overall = _union_bbox(bboxes) if bboxes else None
        sub_extents = list(bboxes)
    else:
        overall = bboxes[0] if bboxes else None
        sub_extents = list(bboxes[1:])
    return {
        "id": collection.get("id"),
        "title": collection.get("title"),
        "description": collection.get("description"),
        "license": collection.get("license"),
        "self": _self_href(collection),
        "bbox": overall,
        "sub_extents": sub_extents,
    }


DEFAULT_LIMIT = 100


def _require_stac(document: dict, url: str) -> dict:
    """A 200 that parsed is not yet a STAC document."""
    if not document.get("id") or not document.get("type"):
        raise GisError(
            CATALOG_MALFORMED,
            f"{url} is JSON but not a STAC document",
            "A STAC item has an 'id' and a 'type'; check the URL",
        )
    return document


def _mode_for(endpoint: str) -> str:
    return stac_fetch.detect_mode(stac_fetch.fetch_json(endpoint))


def list_collections(catalog: str) -> dict:
    """Collections a catalogue offers, in whichever mode it supports."""
    endpoint = resolve_endpoint(catalog)
    mode = _mode_for(endpoint)
    if mode == "search":
        raw = stac_fetch.list_collections_api(endpoint)
        truncated, used = False, 1
    else:
        walked = stac_fetch.traverse(
            endpoint, collection=None, bbox=None, datetime_spec=None, limit=0,
            fetch=stac_fetch.fetch_json,
        )
        raw, truncated, used = walked["collections"], walked["truncated"], walked["requests_used"]
    return {
        "catalog": endpoint,
        "mode": mode,
        "collections": [flatten_collection(c) for c in raw],
        "truncated": truncated,
        "requests_used": used,
    }


def search_items(
    catalog: str,
    *,
    collection: str | None = None,
    bbox: list[float] | None = None,
    datetime_spec: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Items matching an area and a time range. Never fetches asset bytes."""
    endpoint = resolve_endpoint(catalog)
    mode = _mode_for(endpoint)
    backend = stac_fetch.search_api if mode == "search" else stac_fetch.traverse
    found = backend(
        endpoint, collection=collection, bbox=bbox, datetime_spec=datetime_spec, limit=limit
    )
    items = [flatten_item(i) for i in found["items"]]
    return {
        "catalog": endpoint,
        "mode": mode,
        "bbox": bbox,
        "datetime": datetime_spec,
        "items": items,
        "items_returned": len(items),
        "requests_used": found["requests_used"],
        "truncated": found["truncated"],
    }


def get_item(item_url: str) -> dict:
    """One item, by the 'self' href that catalog-search returns."""
    document = _require_stac(stac_fetch.fetch_json(item_url), item_url)
    return {"item_url": item_url, "item": flatten_item(document)}


def get_assets(item_url: str, *, role: str | None = None, media_type: str | None = None) -> dict:
    """An item's assets: hrefs, advertised metadata, and what can read them."""
    document = _require_stac(stac_fetch.fetch_json(item_url), item_url)
    properties = document.get("properties") or {}
    assets = [
        flatten_asset(key, asset, properties, item_url=item_url, item_id=document.get("id"))
        for key, asset in (document.get("assets") or {}).items()
    ]
    if role:
        assets = [a for a in assets if role in a["roles"]]
    if media_type:
        assets = [a for a in assets if a["media_type"] == media_type]
    return {
        "item_url": item_url,
        "item_id": document.get("id"),
        "assets": sorted(assets, key=lambda a: a["key"]),
        "asset_count": len(assets),
    }
