from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_gis.common import crs_status, ensure_workspace_dirs, run_command, utc_now, work_root, write_json
from llm_gis.errors import UNSUPPORTED_FORMAT, GisError
from llm_gis.errors import INPUT_NOT_FOUND, GisError


def _extract_vector_extent(payload: dict[str, Any]) -> dict[str, float] | None:
    mins: list[float] = []
    maxs: list[float] = []
    minys: list[float] = []
    maxys: list[float] = []
    for layer in payload.get("layers", []):
        extent = layer.get("geometryFields", [{}])[0].get("extent")
        if not extent:
            continue
        if isinstance(extent, list) and len(extent) >= 4:
            mins.append(float(extent[0]))
            minys.append(float(extent[1]))
            maxs.append(float(extent[2]))
            maxys.append(float(extent[3]))
        elif isinstance(extent, dict):
            mins.append(float(extent.get("minX", 0.0)))
            maxs.append(float(extent.get("maxX", 0.0)))
            minys.append(float(extent.get("minY", 0.0)))
            maxys.append(float(extent.get("maxY", 0.0)))
    if not mins:
        return None
    return {"minx": min(mins), "maxx": max(maxs), "miny": min(minys), "maxy": max(maxys)}


def _extract_raster_extent(payload: dict[str, Any]) -> dict[str, float] | None:
    corners = payload.get("cornerCoordinates", {})
    if not corners:
        return None
    values = [
        corners.get("lowerLeft"),
        corners.get("lowerRight"),
        corners.get("upperLeft"),
        corners.get("upperRight"),
    ]
    xs = [float(v[0]) for v in values if v]
    ys = [float(v[1]) for v in values if v]
    if not xs or not ys:
        return None
    return {"minx": min(xs), "maxx": max(xs), "miny": min(ys), "maxy": max(ys)}


def inspect_dataset(input_path: Path, ingest_id: str | None = None) -> dict[str, Any]:
    ensure_workspace_dirs()
    if not input_path.exists():
        raise GisError(
            INPUT_NOT_FOUND,
            f"Input path does not exist: {input_path}",
            "Check the path and try again",
        )

    vector_out: dict[str, Any] | None = None
    raster_out: dict[str, Any] | None = None

    try:
        vector_out = json.loads(run_command(["ogrinfo", "-json", "-ro", str(input_path)]))
    except Exception:
        vector_out = None

    try:
        raster_out = json.loads(run_command(["gdalinfo", "-json", str(input_path)]))
    except Exception:
        raster_out = None

    if not vector_out and not raster_out:
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"Neither ogrinfo nor gdalinfo could read {input_path}",
            "Confirm the file is a GDAL-readable vector or raster; for a sidecar format ensure companion files are present",
        )

    if vector_out:
        extent = _extract_vector_extent(vector_out)
        field = vector_out.get("layers", [{}])[0].get("geometryFields", [{}])[0]
        coordinate_system = field.get("coordinateSystem") or {}
        projjson_id = (coordinate_system.get("projjson") or {}).get("id") or {}
        authority = projjson_id.get("authority")
        code = projjson_id.get("code")
        crs_text = f"{authority}:{code}" if authority and code else coordinate_system.get("wkt")
        status, reasons = crs_status(crs_text, extent)
        report = {
            "dataset_kind": "vector",
            "input_path": str(input_path),
            "layers": [
                {
                    "name": layer.get("name"),
                    "geometry_type": (layer.get("geometryFields", [{}])[0] or {}).get("type"),
                    "feature_count": layer.get("featureCount"),
                }
                for layer in vector_out.get("layers", [])
            ],
            "detected_crs": crs_text,
            "extent": extent,
            "crs_status": status,
            "crs_reasons": reasons,
            "raw": vector_out,
            "created_at": utc_now(),
        }
    else:
        extent = _extract_raster_extent(raster_out or {})
        crs_text = (raster_out or {}).get("coordinateSystem", {}).get("wkt")
        status, reasons = crs_status(crs_text, extent)
        report = {
            "dataset_kind": "raster",
            "input_path": str(input_path),
            "size": (raster_out or {}).get("size"),
            "bands": [
                {
                    "band": band.get("band"),
                    "type": band.get("type"),
                    "nodata": band.get("noDataValue"),
                }
                for band in (raster_out or {}).get("bands", [])
            ],
            "detected_crs": crs_text,
            "extent": extent,
            "crs_status": status,
            "crs_reasons": reasons,
            "raw": raster_out,
            "created_at": utc_now(),
        }

    if ingest_id:
        write_json(work_root() / "reports" / f"{ingest_id}.json", report)
    return report
