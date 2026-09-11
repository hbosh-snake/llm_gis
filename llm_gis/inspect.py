from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_gis.asset import LOCAL_FILE, REMOTE_URI, Asset, Band, Layer, Provenance
from llm_gis.common import (
    normalize_crs,
    crs_status,
    crs_text_from_ogr_coordinate_system,
    ensure_workspace_dirs,
    gdal_uri,
    is_remote,
    remote_read_error,
    run_command,
    utc_now,
    work_root,
    write_json,
)
from llm_gis.errors import INPUT_NOT_FOUND, UNSUPPORTED_FORMAT, GisError


def _extract_vector_extent(payload: dict[str, Any]) -> dict[str, float] | None:
    mins: list[float] = []
    maxs: list[float] = []
    minys: list[float] = []
    maxys: list[float] = []
    for layer in payload.get("layers", []):
        fields = layer.get("geometryFields") or [{}]
        extent = fields[0].get("extent")
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


def _build_vector_asset(source: str, payload: dict[str, Any]) -> Asset:
    """What ogrinfo measured, as an Asset.

    `record_count` stays None: there is only a count per layer here, and summing
    them would publish a number no caller has ever been given.
    """
    extent = _extract_vector_extent(payload)
    first_layer = (payload.get("layers") or [{}])[0]
    field = (first_layer.get("geometryFields") or [{}])[0]
    crs_text = normalize_crs(crs_text_from_ogr_coordinate_system(field.get("coordinateSystem") or {}))
    status, reasons = crs_status(crs_text, extent)
    return Asset(
        uri=source,
        provenance=Provenance(
            REMOTE_URI if is_remote(source) else LOCAL_FILE, retrieved_at=utc_now()
        ),
        dataset_kind="vector",
        crs=crs_text,
        crs_status=status,
        crs_reasons=reasons,
        bbox=extent,
        layers=[
            Layer(
                layer.get("name"),
                ((layer.get("geometryFields") or [{}])[0] or {}).get("type"),
                layer.get("featureCount"),
            )
            for layer in payload.get("layers", [])
        ],
        raw=payload,
    )


def _build_raster_asset(source: str, payload: dict[str, Any]) -> Asset:
    """What gdalinfo measured, as an Asset."""
    extent = _extract_raster_extent(payload)
    crs_text = normalize_crs(payload.get("coordinateSystem", {}).get("wkt"))
    status, reasons = crs_status(crs_text, extent)
    return Asset(
        uri=source,
        provenance=Provenance(
            REMOTE_URI if is_remote(source) else LOCAL_FILE, retrieved_at=utc_now()
        ),
        dataset_kind="raster",
        crs=crs_text,
        crs_status=status,
        crs_reasons=reasons,
        bbox=extent,
        size=payload.get("size"),
        bands=[
            Band(band.get("band"), band.get("type"), band.get("noDataValue"))
            for band in payload.get("bands", [])
        ],
        raw=payload,
    )


def _to_report(asset: Asset) -> dict[str, Any]:
    """The historic inspect keys, unchanged.

    Canonical names map back here: uri to input_path, bbox to extent, crs to
    detected_crs, retrieved_at to created_at. The vector and raster branches
    differ only in whether layers or size-and-bands appear.
    """
    report: dict[str, Any] = {
        "dataset_kind": asset.dataset_kind,
        "input_path": asset.uri,
    }
    if asset.dataset_kind == "vector":
        report["layers"] = [
            {"name": l.name, "geometry_type": l.geometry_type, "feature_count": l.feature_count}
            for l in asset.layers
        ]
    else:
        report["size"] = asset.size
        report["bands"] = [
            {"band": b.band, "type": b.type, "nodata": b.nodata} for b in asset.bands
        ]
    report["detected_crs"] = asset.crs
    report["extent"] = asset.bbox
    report["crs_status"] = asset.crs_status
    report["crs_reasons"] = asset.crs_reasons
    report["raw"] = asset.raw
    report["created_at"] = asset.provenance.retrieved_at
    return report


def inspect_dataset(source: str | Path, ingest_id: str | None = None) -> dict[str, Any]:
    """Measure a dataset. `source` is a local path or a remote http/https/s3 URI."""
    ensure_workspace_dirs()
    source = str(source)
    if not is_remote(source) and not Path(source).exists():
        raise GisError(
            INPUT_NOT_FOUND,
            f"Input path does not exist: {source}",
            "Check the path and try again",
        )
    target = gdal_uri(source)

    vector_out: dict[str, Any] | None = None
    raster_out: dict[str, Any] | None = None

    try:
        vector_out = json.loads(run_command(["ogrinfo", "-json", "-ro", target]))
    except Exception:
        vector_out = None

    remote_failure: GisError | None = None
    try:
        raster_out = json.loads(run_command(["gdalinfo", "-json", target]))
    except GisError as error:
        remote_failure = error
        raster_out = None
    except Exception:
        raster_out = None

    if not vector_out and not raster_out:
        if is_remote(source) and remote_failure is not None:
            raise remote_read_error(source, remote_failure)
        hint = "Confirm the file is a GDAL-readable vector or raster; for a sidecar format ensure companion files are present"
        if str(source).lower().endswith(".parquet"):
            hint = "Parquet files cannot be ingested directly. If this is the output of duck-query, regenerate it with --format geopackage instead"
        raise GisError(
            UNSUPPORTED_FORMAT,
            f"Neither ogrinfo nor gdalinfo could read {source}",
            hint,
        )

    if vector_out:
        asset = _build_vector_asset(source, vector_out)
    else:
        asset = _build_raster_asset(source, raster_out or {})
    report = _to_report(asset)

    if ingest_id:
        write_json(work_root() / "reports" / f"{ingest_id}.json", report)
    return report
