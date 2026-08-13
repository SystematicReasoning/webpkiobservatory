"""Property tests for deterministic posture scoring.

The scoring layer is intentionally entity-agnostic. Tests use synthetic records
and algorithmic invariants rather than named organizations or individual expert
judgments.
"""

from __future__ import annotations

import copy
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from compute_als import analyze_bug_record, compute_als


def _sig(**overrides):
    base = {
        "accel": 1.0,
        "year_density": 1.0,
        "n_chronic": 0,
        "n_solo_chronic": 0,
        "chronic_span_avg": 0.0,
        "self_pct": 100.0,
        "gov_frac": 0.0,
        "n": 20,
        "avg_knowledge_weight": 1.0,
        "n_closed_loop": 0,
        "n_broken_promise": 0,
        "severity_score": 0.0,
        "recency_score": 0.0,
    }
    base.update(overrides)
    return base


def _bug(bug_id: int, filed: str, tag: str, self_reported: bool = True):
    return {
        "id": bug_id,
        "filed": filed,
        "whiteboard": f"[ca-compliance] [{tag}]",
        "self_reported": self_reported,
    }


def test_compute_als_is_deterministic_for_identical_inputs():
    sig = _sig(
        accel=2.25,
        year_density=3.0,
        n_chronic=3,
        n_solo_chronic=2,
        chronic_span_avg=4.0,
        self_pct=35.0,
        gov_frac=0.25,
        severity_score=0.35,
        recency_score=0.40,
    )
    first = compute_als(copy.deepcopy(sig))
    second = compute_als(copy.deepcopy(sig))
    assert first == second


def test_audit_context_does_not_change_score():
    sig = _sig(accel=1.8, n_chronic=2, n_solo_chronic=2, self_pct=40.0)
    baseline = compute_als(copy.deepcopy(sig))
    with_context = compute_als(
        copy.deepcopy(sig),
        {
            "transparency_gap": {"gap_level": "high"},
            "staleness": 900,
            "letter_quality_score": {"overall": 10},
        },
    )
    assert baseline["total"] == with_context["total"]
    assert baseline["mode_A"] == with_context["mode_A"]
    assert baseline["mode_B"] == with_context["mode_B"]


def test_lower_self_detection_cannot_reduce_score():
    high_detection = compute_als(_sig(self_pct=90.0))
    low_detection = compute_als(_sig(self_pct=10.0))
    assert low_detection["total"] >= high_detection["total"]


def test_more_structural_recurrence_cannot_reduce_score():
    low = compute_als(_sig(n_chronic=1, n_solo_chronic=1, chronic_span_avg=3.0))
    high = compute_als(_sig(n_chronic=5, n_solo_chronic=5, chronic_span_avg=7.0))
    assert high["total"] >= low["total"]


def test_higher_severity_cannot_reduce_structural_score():
    low = compute_als(
        _sig(n_chronic=3, n_solo_chronic=3, chronic_span_avg=5.0, severity_score=0.05)
    )
    high = compute_als(
        _sig(n_chronic=3, n_solo_chronic=3, chronic_span_avg=5.0, severity_score=0.80)
    )
    assert high["mode_B"] >= low["mode_B"]


def test_higher_recent_severity_cannot_reduce_acceleration_boost():
    low = compute_als(_sig(accel=3.0, recency_score=0.05))
    high = compute_als(_sig(accel=3.0, recency_score=0.80))
    assert high["accel_boost"] >= low["accel_boost"]


def test_fixed_threshold_is_source_neutral():
    result = compute_als(_sig())
    assert result["threshold"] == 48


def test_analysis_date_makes_recency_reproducible():
    bugs = [
        _bug(1, "2025-06-01", "dv-misissuance"),
        _bug(2, "2026-06-01", "ca-misissuance"),
    ]
    as_of = date(2026, 8, 12)
    first = analyze_bug_record(copy.deepcopy(bugs), as_of=as_of)
    second = analyze_bug_record(copy.deepcopy(bugs), as_of=as_of)
    assert first == second
    assert first is not None
    assert first["n_recent"] == 1
    assert first["recency_score"] > 0


def test_severity_scale_is_monotonic_on_synthetic_records():
    as_of = date(2026, 8, 12)
    low = analyze_bug_record(
        [
            _bug(1, "2025-01-01", "dv-misissuance"),
            _bug(2, "2026-01-01", "dv-misissuance"),
        ],
        as_of=as_of,
    )
    high = analyze_bug_record(
        [
            _bug(1, "2025-01-01", "dv-misissuance"),
            _bug(2, "2026-01-01", "ca-misissuance"),
        ],
        as_of=as_of,
    )
    assert low is not None and high is not None
    assert high["severity_score"] > low["severity_score"]


def test_same_day_same_class_batch_is_collapsed_deterministically():
    as_of = date(2026, 8, 12)
    bugs = [
        _bug(1, "2025-05-01", "audit-finding"),
        _bug(2, "2025-05-01", "audit-finding"),
        _bug(3, "2025-05-01", "audit-finding"),
        _bug(4, "2026-05-01", "policy-failure"),
    ]
    result = analyze_bug_record(bugs, as_of=as_of)
    assert result is not None
    assert result["n_orig"] == 4
    assert result["n"] == 2
    assert result["batches_collapsed"] == 2


def test_scores_are_non_negative():
    variants = [
        _sig(),
        _sig(accel=0.5, self_pct=100.0),
        _sig(accel=8.0, self_pct=0.0, n_chronic=8, n_solo_chronic=8,
             chronic_span_avg=10.0, severity_score=1.0, recency_score=1.0),
    ]
    for sig in variants:
        result = compute_als(sig)
        assert result["total"] >= 0
        assert result["mode_A"] >= 0
        assert result["mode_B"] >= 0
        assert result["accel_boost"] >= 0
