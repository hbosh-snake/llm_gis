"""Deterministic quality control over a dataset or a table.

Metrics are collected by llm_gis.qc_collect; everything here is pure. A check
reports pass, warn, or not_evaluated, and never guesses at context it was not
given: an unsupplied comparison is not a passing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pyproj import Transformer

from llm_gis.common import crs_status, parse_crs, utc_now
from llm_gis.errors import CRS_MISSING, CRS_SUSPICIOUS

SEVERITY = "warning"


@dataclass(frozen=True)
class QcContext:
    """What the caller declared about the job that produced this data."""

    expect_non_empty: bool = False
    metric_op: bool = False
    id_column: str | None = None
    reference: dict[str, Any] | None = None


def _result(code: str, result: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": SEVERITY, "result": result, "message": message}


def reproject_bbox(bbox: dict[str, float] | None, src_crs: str | None, dst_crs: str | None) -> dict[str, float] | None:
    """Transform a bbox, densifying the edges so a curved edge is not clipped off."""
    if bbox is None or not src_crs or not dst_crs or src_crs == dst_crs:
        return bbox
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    minx, miny, maxx, maxy = transformer.transform_bounds(
        bbox["minx"], bbox["miny"], bbox["maxx"], bbox["maxy"]
    )
    return {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy}


def _intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    return not (
        a["maxx"] < b["minx"] or b["maxx"] < a["minx"] or a["maxy"] < b["miny"] or b["maxy"] < a["miny"]
    )


def check_crs_missing(metrics: dict, context: QcContext) -> dict:
    status, _ = crs_status(metrics.get("crs"), metrics.get("bbox"))
    if status == "missing":
        return _result(CRS_MISSING, "warn", "No CRS detected on this dataset")
    return _result(CRS_MISSING, "pass", f"CRS present: {metrics.get('crs')}")


def check_crs_suspicious(metrics: dict, context: QcContext) -> dict:
    status, reasons = crs_status(metrics.get("crs"), metrics.get("bbox"))
    if status == "suspicious":
        return _result(CRS_SUSPICIOUS, "warn", "; ".join(reasons))
    if status == "missing":
        return _result(CRS_SUSPICIOUS, "not_evaluated", "No CRS to judge")
    return _result(CRS_SUSPICIOUS, "pass", "CRS is plausible for the extent")


def check_geographic_crs_for_metric_operation(metrics: dict, context: QcContext) -> dict:
    code = "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION"
    if not context.metric_op:
        return _result(code, "not_evaluated", "No metric operation declared; pass --metric-op to check")
    crs = parse_crs(metrics.get("crs"))
    if crs is None:
        return _result(code, "not_evaluated", "CRS absent or unparseable")
    if crs.is_geographic:
        return _result(code, "warn", f"{metrics.get('crs')} is geographic; areas and distances will be in degrees")
    return _result(code, "pass", f"{metrics.get('crs')} is projected")


def check_empty_result_unexpected(metrics: dict, context: QcContext) -> dict:
    code = "EMPTY_RESULT_UNEXPECTED"
    vector = metrics.get("vector")
    if vector is None:
        return _result(code, "not_evaluated", "Not a vector dataset")
    if not context.expect_non_empty:
        return _result(code, "not_evaluated", "Emptiness not declared unexpected; pass --expect-non-empty to check")
    if vector["feature_count"] == 0:
        return _result(code, "warn", "Result has no features, but features were expected")
    return _result(code, "pass", f"{vector['feature_count']} features present")


def check_result_bbox_disjoint_from_input(metrics: dict, context: QcContext) -> dict:
    code = "RESULT_BBOX_DISJOINT_FROM_INPUT"
    reference = context.reference
    if reference is None:
        return _result(code, "not_evaluated", "No reference given; pass --compare-to to check")
    subject_bbox = metrics.get("bbox")
    if subject_bbox is None or reference.get("bbox") is None:
        return _result(code, "not_evaluated", "One of the two extents is empty")
    reference_bbox = reproject_bbox(reference["bbox"], reference.get("crs"), metrics.get("crs"))
    if reference_bbox is None:
        return _result(code, "not_evaluated", "Reference extent could not be reprojected")
    if _intersects(subject_bbox, reference_bbox):
        return _result(code, "pass", f"Extent overlaps {reference['ref']}")
    return _result(code, "warn", f"Extent does not overlap {reference['ref']} at all")


CHECKS: list[Callable[[dict, QcContext], dict]] = [
    check_crs_missing,
    check_crs_suspicious,
    check_geographic_crs_for_metric_operation,
    check_empty_result_unexpected,
    check_result_bbox_disjoint_from_input,
]


def build_report(source: dict, metrics: dict, context: QcContext) -> dict[str, Any]:
    """Run every check and assemble the envelope."""
    checks = [check(metrics, context) for check in CHECKS]
    warnings = [
        {"code": c["code"], "message": c["message"], "severity": c["severity"]}
        for c in checks
        if c["result"] == "warn"
    ]
    return {
        "qc_status": "warning" if warnings else "ok",
        "source": source,
        "metrics": metrics,
        "checks": checks,
        "warnings": warnings,
        "created_at": utc_now(),
    }
