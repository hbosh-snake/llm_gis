"""A deterministic picture of a dataset, for a reader that has eyes.

Numbers hide three failures that a picture does not: coordinates given in the wrong
order, an AOI that misses the data entirely, and features nowhere near the AOI. The
frame is always EPSG:4326 with a drawn graticule, so all three are visible in one
image: wrong graticule cell, clear space between two shapes, or a small box beside a
sprawl.

Nothing here measures. Metrics come from qc_collect, the same collectors bin/qc judges.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from llm_gis import qc_collect
from llm_gis.common import (
    ensure_workspace_dirs,
    gdal_uri,
    is_remote,
    reproject_bbox,
    run_command,
    utc_now,
    work_root,
)

WGS84 = "EPSG:4326"
SIZE = 512
PAD = 0.05
MIN_SPAN = 0.001
GRATICULE_DEGREES = 1
RASTER_SUFFIXES = {".tif", ".tiff", ".vrt", ".img", ".jp2"}


def _union(a: dict[str, float], b: dict[str, float] | None) -> dict[str, float]:
    if not b:
        return dict(a)
    return {
        "minx": min(a["minx"], b["minx"]),
        "miny": min(a["miny"], b["miny"]),
        "maxx": max(a["maxx"], b["maxx"]),
        "maxy": max(a["maxy"], b["maxy"]),
    }


def frame(dataset_bbox: dict[str, float], aoi_bbox: dict[str, float] | None) -> dict[str, Any]:
    """The rendered extent: the union, padded, squared, never zero-sized.

    Zero span is the degenerate case a single point or a single-row raster produces;
    a frame with no width cannot be rendered, so MIN_SPAN floors it.
    """
    box = _union(dataset_bbox, aoi_bbox)
    span = max(box["maxx"] - box["minx"], box["maxy"] - box["miny"], MIN_SPAN)
    pad = span * PAD
    cx = (box["minx"] + box["maxx"]) / 2
    cy = (box["miny"] + box["maxy"]) / 2
    half = span / 2 + pad
    return {
        "bbox_4326": {
            "minx": cx - half, "miny": cy - half, "maxx": cx + half, "maxy": cy + half,
        },
        "size": [SIZE, SIZE],
        "resampling": "nearest",
    }


def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["maxx"] < b["minx"] or b["maxx"] < a["minx"]
        or a["maxy"] < b["miny"] or b["maxy"] < a["miny"]
    )


def _kind(dataset: str) -> str:
    if is_remote(dataset):
        return "raster"
    return "raster" if Path(dataset).suffix.lower() in RASTER_SUFFIXES else "vector"


def _metrics(dataset: str, kind: str) -> dict[str, Any]:
    if kind == "raster":
        return qc_collect.file_raster_metrics(dataset, False)
    return qc_collect.file_vector_metrics(Path(dataset), None)


def _graticule(box: dict[str, float], destination: Path) -> Path:
    """Whole-degree lines as GeoJSON, computed rather than downloaded."""
    import math

    lines = []
    for x in range(math.floor(box["minx"]), math.ceil(box["maxx"]) + 1, GRATICULE_DEGREES):
        lines.append([[x, box["miny"]], [x, box["maxy"]]])
    for y in range(math.floor(box["miny"]), math.ceil(box["maxy"]) + 1, GRATICULE_DEGREES):
        lines.append([[box["minx"], y], [box["maxx"], y]])
    payload = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": c}}
            for c in lines
        ],
    }
    destination.write_text(json.dumps(payload), encoding="utf-8")
    return destination


def _blank(box: dict[str, float], destination: Path) -> Path:
    """One empty Byte channel on the frame's grid. Every channel shares this grid."""
    run_command([
        "gdal_create", "-q", "-outsize", str(SIZE), str(SIZE), "-bands", "1",
        "-ot", "Byte", "-burn", "0", "-a_srs", WGS84,
        "-a_ullr", str(box["minx"]), str(box["maxy"]), str(box["maxx"]), str(box["miny"]),
        str(destination),
    ])
    return destination


def _burn(source: str, channel: Path, work_dir: Path, name: str, outline: bool) -> None:
    """Reproject to 4326 and burn into a channel: an outline, or a fill."""
    prepared = work_dir / f"{name}.geojson"
    args = ["ogr2ogr", "-q", "-t_srs", WGS84, "-f", "GeoJSON"]
    if outline:
        args += ["-nlt", "MULTILINESTRING"]
    run_command([*args, str(prepared), gdal_uri(source)])
    run_command([
        "gdal_rasterize", "-q", "-b", "1", "-burn", "255", str(prepared), str(channel),
    ])


def _raster_channel(dataset: str, box: dict[str, float], scale: dict, work_dir: Path, name: str) -> Path:
    """The data, warped onto the frame's grid and scaled to Byte by measured bounds.

    The scale bounds come from the measured statistics, never from a per-run guess:
    that is what makes two renders of the same input identical byte for byte.
    """
    warped = work_dir / f"{name}.warped.tif"
    run_command([
        "gdalwarp", "-q", "-overwrite", "-t_srs", WGS84,
        "-te", str(box["minx"]), str(box["miny"]), str(box["maxx"]), str(box["maxy"]),
        "-ts", str(SIZE), str(SIZE), "-r", "nearest",
        gdal_uri(dataset), str(warped),
    ])
    channel = work_dir / f"{name}.red.tif"
    low, high = scale["min"], scale["max"]
    if low is None or high is None or low == high:
        low, high = 0.0, 1.0
    run_command([
        "gdal_translate", "-q", "-ot", "Byte",
        "-scale", str(low), str(high), "0", "255",
        "-b", "1", str(warped), str(channel),
    ])
    return channel


def render(
    dataset: str,
    *,
    aoi: str | None = None,
    output: str | None = None,
) -> dict[str, Any]:
    """Write a PNG and its sidecar. Same input, same bytes.

    Three single-band channels are built on one grid and stacked with
    `gdalbuildvrt -separate`, which is a description rather than a copy, then written
    once as PNG. Nothing is composited in Python and no image library is needed.
    """
    ensure_workspace_dirs()
    kind = _kind(dataset)
    metrics = _metrics(dataset, kind)
    data_bbox = reproject_bbox(metrics["bbox"], metrics["crs"], WGS84)

    aoi_bbox = None
    if aoi:
        aoi_metrics = _metrics(aoi, _kind(aoi))
        aoi_bbox = reproject_bbox(aoi_metrics["bbox"], aoi_metrics["crs"], WGS84)

    computed = frame(data_bbox, aoi_bbox)
    box = computed["bbox_4326"]

    stem = Path(output) if output else work_root() / "preview" / Path(dataset).stem
    stem.parent.mkdir(parents=True, exist_ok=True)
    # Use a temporary directory for all GDAL intermediates; keep only the final PNG and sidecar
    work_dir = Path(tempfile.mkdtemp(prefix="preview_", dir=work_root() / "tmp"))
    name = stem.name

    scale = {"min": None, "max": None}
    if kind == "raster":
        band = ((metrics.get("raster") or {}).get("bands") or [{}])[0]
        scale = {"min": band.get("min"), "max": band.get("max")}
        red = _raster_channel(dataset, box, scale, work_dir, name)
    else:
        red = _blank(box, work_dir / f"{name}.red.tif")
        _burn(dataset, red, work_dir, f"{name}.data", outline=False)

    green = _blank(box, work_dir / f"{name}.green.tif")
    if aoi:
        _burn(aoi, green, work_dir, f"{name}.aoi", outline=True)

    blue = _blank(box, work_dir / f"{name}.blue.tif")
    graticule = _graticule(box, work_dir / f"{name}.graticule.geojson")
    run_command([
        "gdal_rasterize", "-q", "-b", "1", "-burn", "255", str(graticule), str(blue),
    ])

    stacked = work_dir / f"{name}.rgb.vrt"
    run_command([
        "gdalbuildvrt", "-q", "-separate", str(stacked), str(red), str(green), str(blue),
    ])
    png = stem.with_suffix(".png")
    run_command(["gdal_translate", "-q", "-of", "PNG", str(stacked), str(png)])

    sidecar_payload = {
        "dataset": {"uri": dataset, "kind": kind},
        "frame": computed,
        "render": {
            "channels": {"r": "data", "g": "aoi", "b": "graticule"},
            "scale": scale,
            "graticule_degrees": GRATICULE_DEGREES,
        },
        "summary": {
            "crs": metrics["crs"],
            "bbox": metrics["bbox"],
            "bbox_4326": data_bbox,
            "bands": (metrics.get("raster") or {}).get("bands") if kind == "raster" else None,
            "aoi_intersects": None if not aoi_bbox else _intersects(data_bbox, aoi_bbox),
        },
        "created_at": utc_now(),
    }
    sidecar = stem.with_suffix(".preview.json")
    sidecar.write_text(json.dumps(sidecar_payload, indent=2, sort_keys=True), encoding="utf-8")

    # Clean up temporary GDAL intermediates
    import shutil
    shutil.rmtree(work_dir, ignore_errors=True)

    return {"png": str(png), "sidecar": str(sidecar), "kind": kind, **sidecar_payload}
