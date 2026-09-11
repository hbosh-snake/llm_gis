"""Deterministic quality control over a dataset or a table.

Metrics are collected by llm_gis.qc_collect; everything here is pure. A check
reports pass, warn, or not_evaluated, and never guesses at context it was not
given: an unsupplied comparison is not a passing one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from llm_gis import qc_collect
from llm_gis.common import crs_status, is_remote, parse_crs, reproject_bbox, utc_now
from llm_gis.errors import CRS_MISSING, CRS_SUSPICIOUS, INPUT_NOT_FOUND, GisError

SEVERITY = "warning"
EMPTY_RESULT_UNEXPECTED = "EMPTY_RESULT_UNEXPECTED"


@dataclass(frozen=True)
class QcContext:
    """What the caller declared about the job that produced this data."""

    expect_non_empty: bool = False
    metric_op: bool = False
    id_column: str | None = None
    reference: dict[str, Any] | None = None


def _result(code: str, result: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": SEVERITY, "result": result, "message": message}


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
    code = EMPTY_RESULT_UNEXPECTED
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


def resolve_source(ref: str) -> dict[str, str]:
    """A path if one exists on disk, otherwise schema.table."""
    if is_remote(ref):
        return {"kind": "file", "ref": ref}
    path = Path(ref)
    if path.exists():
        return {"kind": "file", "ref": ref}
    if "." in ref and "/" not in ref:
        schema, table = ref.split(".", 1)
        return {"kind": "postgis_table", "ref": ref, "schema": schema, "table": table}
    raise GisError(
        INPUT_NOT_FOUND,
        f"No file at {ref}, and it is not a schema.table reference",
        "Pass a path under /data, or a table like analysis_<ingest_id>.result",
    )


def qc_report(
    ref: str, context: QcContext, *, exact_stats: bool = False, bbox: dict | None = None
) -> dict[str, Any]:
    """Collect metrics for one source and judge them against the declared context."""
    resolved = resolve_source(ref)
    if resolved["kind"] == "file":
        source, metrics = qc_collect.file_metrics(ref, context.id_column, exact_stats, bbox)
    else:
        source, metrics = qc_collect.table_metrics(
            resolved["schema"], resolved["table"], context.id_column
        )
    return build_report(source, metrics, context)


def reference_for(ref: str) -> dict[str, Any]:
    """The CRS and extent of a comparison source, collected the same way as the subject."""
    resolved = resolve_source(ref)
    if resolved["kind"] == "file":
        _, metrics = qc_collect.file_metrics(Path(ref), None, False)
    else:
        _, metrics = qc_collect.table_metrics(resolved["schema"], resolved["table"], None)
    return {"ref": ref, "crs": metrics["crs"], "bbox": metrics["bbox"]}
