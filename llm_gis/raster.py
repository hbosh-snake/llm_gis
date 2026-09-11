"""Read an area of interest out of a raster without downloading it.

A window is a VRT: a description of which pixels are wanted, measured at under two
kilobytes for a Sentinel-2 AOI. Statistics and zonal statistics run against that VRT,
so a remote scene crosses the network as range requests over the window alone.
Pixels are written only when the caller names an --output, which is the whole of
"materialise only when required" for raster.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from llm_gis.common import (
    ensure_workspace_dirs,
    gdal_uri,
    normalize_crs,
    reproject_bbox,
    run_command,
    utc_now,
    work_root,
    write_json,
)
from llm_gis.errors import MISSING_ARGUMENT, GisError

WGS84 = "EPSG:4326"


def _as_bbox(values: tuple[float, float, float, float]) -> dict[str, float]:
    minx, miny, maxx, maxy = (float(v) for v in values)
    if minx >= maxx or miny >= maxy:
        raise GisError(
            MISSING_ARGUMENT,
            f"Bounding box is empty or inverted: {values}",
            "Give it as minx,miny,maxx,maxy in the CRS named by --bbox-crs",
            {"bbox": list(values)},
        )
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def _info(target: str, *, stats: bool = False) -> dict[str, Any]:
    """gdalinfo as JSON. PAM is disabled: a .aux.xml beside a read-only source fails."""
    args = ["gdalinfo", "-json"]
    if stats:
        args.append("-stats")
    env = {**os.environ, "GDAL_PAM_ENABLED": "NO"}
    return json.loads(run_command([*args, target], env=env))


def _extent(payload: dict[str, Any]) -> dict[str, float] | None:
    corners = payload.get("cornerCoordinates") or {}
    xs = [float(c[0]) for c in corners.values() if c]
    ys = [float(c[1]) for c in corners.values() if c]
    if not xs:
        return None
    return {"minx": min(xs), "miny": min(ys), "maxx": max(xs), "maxy": max(ys)}


def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["maxx"] < b["minx"] or b["maxx"] < a["minx"]
        or a["maxy"] < b["miny"] or b["maxy"] < a["miny"]
    )


def window_vrt(
    source: str,
    bbox: dict[str, float],
    bbox_crs: str,
    t_srs: str | None,
    work_dir: Path,
) -> Path:
    """Describe the window as a VRT. No pixels are read or written by this call.

    -projwin_srs lets GDAL do the corner transform itself, so the AOI is never
    silently interpreted in the raster's own units.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    destination = work_dir / "window.vrt"
    args = [
        "gdal_translate", "-q", "-of", "VRT",
        "-projwin_srs", bbox_crs,
        "-projwin", str(bbox["minx"]), str(bbox["maxy"]), str(bbox["maxx"]), str(bbox["miny"]),
    ]
    if t_srs:
        args = ["gdalwarp", "-q", "-of", "VRT", "-t_srs", t_srs,
                "-te_srs", bbox_crs,
                "-te", str(bbox["minx"]), str(bbox["miny"]), str(bbox["maxx"]), str(bbox["maxy"])]
    run_command([*args, gdal_uri(source), str(destination)])
    return destination


def band_stats(target: str) -> list[dict[str, Any]]:
    """Exact statistics over whatever the target covers, which is the window."""
    payload = _info(target, stats=True)
    bands = []
    for band in payload.get("bands", []):
        metadata = (band.get("metadata") or {}).get("", {})
        valid_percent = metadata.get("STATISTICS_VALID_PERCENT")
        bands.append(
            {
                "index": band.get("band"),
                "nodata": band.get("noDataValue"),
                "min": band.get("minimum"),
                "max": band.get("maximum"),
                "mean": band.get("mean"),
                "stdev": band.get("stdDev"),
                "percent_nodata": None if valid_percent is None else 100.0 - float(valid_percent),
            }
        )
    return bands


DEFAULT_ZONE_STATS = ["count", "mean", "min", "max", "stdev"]


def _vector_crs(path: str) -> str | None:
    payload = json.loads(run_command(["ogrinfo", "-json", "-ro", gdal_uri(path)]))
    layer = (payload.get("layers") or [{}])[0]
    field = (layer.get("geometryFields") or [{}])[0]
    from llm_gis.common import crs_text_from_ogr_coordinate_system

    return normalize_crs(crs_text_from_ogr_coordinate_system(field.get("coordinateSystem") or {}))


def _vector_fields(path: str) -> list[str]:
    """Attribute field names, so the zone's own columns ride along in the output.

    `gdal raster zonal-stats` carries no zone attribute through unless named with
    --include-field, so the fields are read here rather than the caller guessing them.
    """
    payload = json.loads(run_command(["ogrinfo", "-json", "-ro", gdal_uri(path)]))
    layer = (payload.get("layers") or [{}])[0]
    return [f["name"] for f in layer.get("fields", [])]


def zonal_stats(
    target: str,
    zones: str,
    stats: list[str],
    work_dir: Path,
    raster_crs: str | None,
) -> list[dict[str, Any]]:
    """Statistics per zone, with the zone CRS reconciled here rather than by GDAL.

    `gdal raster zonal-stats` warns on an SRS mismatch and computes anyway, which is a
    silently wrong answer waiting to happen. We reproject first, so the warning cannot fire.
    """
    zone_crs = _vector_crs(zones)
    prepared = zones
    if raster_crs and zone_crs and zone_crs != raster_crs:
        prepared = str(work_dir / "zones.gpkg")
        run_command([
            "ogr2ogr", "-q", "-t_srs", raster_crs, "-f", "GPKG", prepared, gdal_uri(zones),
        ])

    destination = work_dir / "zonal.geojson"
    args = ["gdal", "raster", "zonal-stats", "-q", "--overwrite",
            "-i", target, "--zones", prepared, "-f", "GeoJSON", "-o", str(destination)]
    for name in stats:
        args += ["--stat", name]
    for name in _vector_fields(prepared):
        args += ["--include-field", name]
    run_command(args)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    return [feature.get("properties", {}) for feature in payload.get("features", [])]


def window(
    source: str,
    *,
    bbox: tuple[float, float, float, float],
    bbox_crs: str = WGS84,
    band: int = 1,
    t_srs: str | None = None,
    stats: bool = True,
    output: str | None = None,
    zones: str | None = None,
    zone_stats: list[str] | None = None,
    ingest_id: str | None = None,
) -> dict[str, Any]:
    """Read one AOI out of a raster. Writes pixels only when `output` is given."""
    ensure_workspace_dirs()
    aoi = _as_bbox(bbox)

    scene = _info(gdal_uri(source))
    scene_crs = normalize_crs((scene.get("coordinateSystem") or {}).get("wkt"))
    scene_bbox = _extent(scene)
    aoi_in_scene = reproject_bbox(aoi, bbox_crs, scene_crs)

    result: dict[str, Any] = {
        "source": source,
        "bbox": aoi,
        "bbox_crs": bbox_crs,
        "crs": scene_crs,
        "size": None,
        "bbox_native": None,
        "bbox_4326": None,
        "aoi_intersects": bool(scene_bbox and aoi_in_scene and _intersects(scene_bbox, aoi_in_scene)),
        "bands": [],
        "zonal": None,
        "output": None,
        "created_at": utc_now(),
    }
    if not result["aoi_intersects"]:
        return _record(result, ingest_id)

    work_dir = work_root() / "raster" / (ingest_id or "window")
    vrt = window_vrt(source, aoi, bbox_crs, t_srs, work_dir)
    measured = _info(str(vrt))
    window_crs = normalize_crs((measured.get("coordinateSystem") or {}).get("wkt"))
    native = _extent(measured)

    result["crs"] = window_crs
    result["size"] = measured.get("size")
    result["bbox_native"] = native
    result["bbox_4326"] = reproject_bbox(native, window_crs, WGS84)
    if stats:
        result["bands"] = band_stats(str(vrt))
    if zones:
        result["zonal"] = zonal_stats(
            str(vrt), zones, zone_stats or DEFAULT_ZONE_STATS, work_dir, window_crs
        )
    if output:
        run_command([
            "gdal_translate", "-q", "-of", "COG", "-co", "COMPRESS=DEFLATE",
            "-b", str(band), str(vrt), output,
        ])
        result["output"] = output
    return _record(result, ingest_id)


def _record(result: dict[str, Any], ingest_id: str | None) -> dict[str, Any]:
    """Provenance for a produced asset, following the analysis.json convention."""
    if ingest_id:
        write_json(work_root() / "reports" / f"{ingest_id}.raster.json", result)
    return result
