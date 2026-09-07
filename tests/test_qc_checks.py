"""Every warning code, driven from literal metrics dicts. No I/O of any kind."""

from __future__ import annotations

import pytest

from llm_gis.qc import QcContext, build_report, reproject_bbox

BBOX = {"minx": 10.0, "miny": 45.0, "maxx": 10.3, "maxy": 45.3}


def _metrics(**overrides) -> dict:
    base = {
        "crs": "EPSG:4326",
        "bbox": dict(BBOX),
        "vector": {
            "feature_count": 4,
            "geometry_types": {"POLYGON": 4},
            "declared_geometry_type": "Polygon",
            "empty_count": 0,
            "invalid_count": 0,
            "has_z": False,
            "has_m": False,
            "area_stats": {"min": 0.01, "max": 0.01, "mean": 0.01, "sum": 0.04},
            "length_stats": None,
            "null_counts": {"name": 0},
            "duplicate_id_count": 0,
            "id_column": "fid",
        },
        "raster": None,
    }
    base.update(overrides)
    return base


def _source(kind: str = "file") -> dict:
    return {"kind": kind, "ref": "/tmp/x.gpkg", "dataset_kind": "vector"}


def _check(report: dict, code: str) -> dict:
    return next(c for c in report["checks"] if c["code"] == code)


def test_a_clean_dataset_with_no_context_is_ok():
    report = build_report(_source(), _metrics(), QcContext())
    assert report["qc_status"] == "ok"
    assert report["warnings"] == []


def test_unsupplied_context_is_not_evaluated_never_pass():
    """The distinction the whole envelope exists for."""
    report = build_report(_source(), _metrics(feature_count=0), QcContext())
    for code in [
        "EMPTY_RESULT_UNEXPECTED",
        "RESULT_BBOX_DISJOINT_FROM_INPUT",
        "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION",
    ]:
        assert _check(report, code)["result"] == "not_evaluated"


def test_crs_missing_warns_without_any_context():
    report = build_report(_source(), _metrics(crs=None), QcContext())
    assert _check(report, "CRS_MISSING")["result"] == "warn"
    assert report["qc_status"] == "warning"
    assert [w["code"] for w in report["warnings"]] == ["CRS_MISSING"]


def test_crs_suspicious_warns_and_carries_the_reason():
    metrics = _metrics(crs="EPSG:3035", bbox=dict(BBOX))
    report = build_report(_source(), metrics, QcContext())
    check = _check(report, "CRS_SUSPICIOUS")
    assert check["result"] == "warn"
    assert "lon/lat" in check["message"]


def test_geographic_crs_warns_only_when_the_operation_is_metric():
    metrics = _metrics()
    assert _check(build_report(_source(), metrics, QcContext()), "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION")["result"] == "not_evaluated"
    warned = build_report(_source(), metrics, QcContext(metric_op=True))
    assert _check(warned, "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION")["result"] == "warn"


def test_projected_crs_passes_a_metric_operation():
    metrics = _metrics(crs="EPSG:3035", bbox={"minx": 4e6, "miny": 2e6, "maxx": 4.1e6, "maxy": 2.1e6})
    report = build_report(_source(), metrics, QcContext(metric_op=True))
    assert _check(report, "GEOGRAPHIC_CRS_FOR_METRIC_OPERATION")["result"] == "pass"


def test_empty_result_warns_only_when_declared_unexpected():
    metrics = _metrics()
    metrics["vector"]["feature_count"] = 0
    report = build_report(_source(), metrics, QcContext(expect_non_empty=True))
    assert _check(report, "EMPTY_RESULT_UNEXPECTED")["result"] == "warn"


def test_a_non_empty_result_passes_the_empty_check():
    report = build_report(_source(), _metrics(), QcContext(expect_non_empty=True))
    assert _check(report, "EMPTY_RESULT_UNEXPECTED")["result"] == "pass"


def test_disjoint_bboxes_warn():
    reference = {"ref": "raw_x.parcels", "crs": "EPSG:4326",
                 "bbox": {"minx": 0.0, "miny": 0.0, "maxx": 1.0, "maxy": 1.0}}
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "warn"


def test_overlapping_bboxes_pass():
    reference = {"ref": "raw_x.parcels", "crs": "EPSG:4326", "bbox": dict(BBOX)}
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "pass"


def test_a_null_bbox_cannot_be_compared():
    reference = {"ref": "raw_x.parcels", "crs": "EPSG:4326", "bbox": None}
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "not_evaluated"


def test_bbox_comparison_crosses_crs():
    """The same ground area in EPSG:3035 must not read as disjoint."""
    reference = {
        "ref": "raw_x.parcels",
        "crs": "EPSG:3035",
        "bbox": reproject_bbox(dict(BBOX), "EPSG:4326", "EPSG:3035"),
    }
    report = build_report(_source(), _metrics(), QcContext(reference=reference))
    assert _check(report, "RESULT_BBOX_DISJOINT_FROM_INPUT")["result"] == "pass"


def test_reproject_bbox_is_a_noop_for_the_same_crs():
    assert reproject_bbox(dict(BBOX), "EPSG:4326", "EPSG:4326") == BBOX


def test_raster_metrics_skip_the_vector_only_checks():
    metrics = {"crs": "EPSG:4326", "bbox": dict(BBOX), "vector": None,
               "raster": {"width": 20, "height": 20, "band_count": 1,
                          "resolution": {"x": 0.01, "y": 0.01}, "bands": [],
                          "stats_mode": "approximate"}}
    source = {"kind": "file", "ref": "/tmp/x.tif", "dataset_kind": "raster"}
    report = build_report(source, metrics, QcContext(expect_non_empty=True))
    assert _check(report, "EMPTY_RESULT_UNEXPECTED")["result"] == "not_evaluated"


def test_every_check_appears_exactly_once():
    report = build_report(_source(), _metrics(), QcContext())
    codes = [c["code"] for c in report["checks"]]
    assert len(codes) == len(set(codes)) == 5


def test_warnings_are_the_warn_subset_in_the_plans_shape():
    report = build_report(_source(), _metrics(crs=None), QcContext())
    warning = report["warnings"][0]
    assert set(warning) == {"code", "message", "severity"}
    assert warning["severity"] == "warning"
