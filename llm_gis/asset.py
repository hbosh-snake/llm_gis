"""One descriptor for anything this workspace can point at.

Three producers describe datasets -- inspect, duck-describe and catalog-assets --
and each grew its own vocabulary for the same facts. This module holds the shape
they have in common, extracted from what they emit rather than imagined ahead of
them: every field here is populated by at least one of the three today.

Top-level fields carry measurements only, meaning something opened the source and
read what was there. A publisher's claims stay under `advertised` and are never
promoted, so a STAC asset nobody has opened reports None for the facts nobody has
checked. That is the model stating its ignorance, not a gap to be filled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

LOCAL_FILE = "local_file"
REMOTE_URI = "remote_uri"
STAC_ASSET = "stac_asset"


@dataclass
class Column:
    """One column of a tabular source, named as the reading engine spells it."""

    name: str
    type: str


@dataclass
class Layer:
    """One vector layer."""

    name: str | None
    geometry_type: str | None
    feature_count: int | None


@dataclass
class Band:
    """One raster band."""

    band: int | None
    type: str | None
    nodata: float | None


@dataclass
class Provenance:
    """Where an asset came from.

    Every field is present always and None where it does not apply, so the block
    never changes shape by source type. `content_hash` is filled only by producers
    that already hash their input; describing a dataset does not hash it.
    """

    source_type: str
    retrieved_at: str | None = None
    catalog_url: str | None = None
    item_id: str | None = None
    asset_key: str | None = None
    content_hash: str | None = None


@dataclass
class Asset:
    """A dataset we can point at: where it is, what it holds, where it came from."""

    uri: str | None
    provenance: Provenance
    dataset_kind: str | None = None
    media_type: str | None = None
    roles: list[str] = field(default_factory=list)
    readable_by: list[str] = field(default_factory=list)
    readers: list[str] = field(default_factory=list)
    crs: str | None = None
    crs_status: str | None = None
    crs_reasons: list[str] = field(default_factory=list)
    bbox: dict[str, float] | None = None
    record_count: int | None = None
    geometry_column: str | None = None
    columns: list[Column] = field(default_factory=list)
    layers: list[Layer] = field(default_factory=list)
    bands: list[Band] = field(default_factory=list)
    size: list[int] | None = None
    advertised: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None
