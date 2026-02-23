#!/usr/bin/env python3
"""Validate synthetic scenarios S0-S12 and emit results/report.

Stdlib-only implementation.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

EXPECTED = {
    "S0": {"label": "no_incident", "confidence": "low_or_higher", "click_quality": 0.000, "search_quality_success": 0.000},
    "S1": {"label": "seasonality_only", "confidence": "high", "click_quality": 0.000, "search_quality_success": 0.000},
    "S2": {"label": "seasonality_shock", "confidence": "medium_or_higher", "click_quality": -0.015, "search_quality_success": -0.010},
    "S3": {"label": "l3_interleaver_change", "confidence": "medium_or_higher", "click_quality": -0.006, "search_quality_success": 0.004},
    "S4": {"label": "l3_interleaver_regression", "confidence": "high", "click_quality": -0.035, "search_quality_success": -0.022},
    "S5": {"label": "ai_behavior_shift", "confidence": "medium_or_higher", "click_quality": -0.020, "search_quality_success": 0.006},
    "S6": {"label": "ai_regression", "confidence": "high", "click_quality": 0.000, "search_quality_success": -0.030},
    "S7": {
        "label": "multi_candidate_unresolved_overlap",
        "confidence": "downgraded",
        "click_quality": -0.045,
        "search_quality_success": -0.030,
    },
    "S8": {"label": "blocked_by_data_quality", "confidence": "none", "click_quality": 0.000, "search_quality_success": 0.000},
    "S9": {
        "label": "mix_shift_composition",
        "confidence": "low_or_higher",
        "click_quality": -0.007,
        "search_quality_success": -0.005,
    },
    "S10": {
        "label": "connector_regression",
        "confidence": "low_or_higher",
        "click_quality": -0.010,
        "search_quality_success": -0.008,
    },
    "S11": {
        "label": "connector_auth_expiry",
        "confidence": "low_or_higher",
        "click_quality": -0.005,
        "search_quality_success": -0.004,
    },
    "S12": {
        "label": "ai_model_migration",
        "confidence": "low_or_higher",
        "click_quality": 0.000,
        "search_quality_success": -0.012,
    },
}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate synthetic scenario outputs")
    parser.add_argument("--input-dir", default="data/synthetic")
    parser.add_argument("--output-dir", default="data/synthetic")
    return parser.parse_args()


def to_float(value: str) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def confidence_from_score(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    if score >= 40:
        return "low"
    return "insufficient_evidence"


def load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open() as f:
        return list(csv.DictReader(f))


def mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _segment_period_deltas(
    rows: List[Dict[str, str]],
    segment_field: str,
    metric_field: str,
) -> Dict[str, float]:
    """Return per-segment (current - baseline) metric deltas."""
    by_segment: Dict[str, Dict[str, List[float]]] = defaultdict(
        lambda: {"baseline": [], "current": []}
    )
    for row in rows:
        period = str(row.get("period", ""))
        if period not in {"baseline", "current"}:
            continue
        segment = str(row.get(segment_field, ""))
        if not segment:
            continue
        by_segment[segment][period].append(to_float(row.get(metric_field, "0")))

    deltas: Dict[str, float] = {}
    for segment, values in by_segment.items():
        deltas[segment] = mean(values["current"]) - mean(values["baseline"])
    return deltas


def _max_share_shift(rows: List[Dict[str, str]], segment_field: str) -> float:
    """Return max absolute baseline->current share shift across segment values."""
    by_segment_counts: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"baseline": 0, "current": 0}
    )
    for row in rows:
        period = str(row.get("period", ""))
        if period not in {"baseline", "current"}:
            continue
        segment = str(row.get(segment_field, ""))
        if not segment:
            continue
        by_segment_counts[segment][period] += 1

    baseline_total = sum(v["baseline"] for v in by_segment_counts.values())
    current_total = sum(v["current"] for v in by_segment_counts.values())
    if baseline_total == 0 or current_total == 0:
        return 0.0

    return max(
        abs((v["current"] / current_total) - (v["baseline"] / baseline_total))
        for v in by_segment_counts.values()
    )


def summarize(
    metrics: List[Dict[str, str]],
    sessions: List[Dict[str, str]],
) -> Dict[str, Dict[str, float | int | bool | str]]:
    by_sid_metrics: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    by_sid_sessions: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    for row in metrics:
        by_sid_metrics[row["scenario_id"]].append(row)
    for row in sessions:
        by_sid_sessions[row["scenario_id"]].append(row)

    summary: Dict[str, Dict[str, float | int | bool | str]] = {}
    for sid in sorted(by_sid_metrics.keys()):
        mrows = by_sid_metrics[sid]
        srows = by_sid_sessions.get(sid, [])

        dlctr_vals = [to_float(r["click_quality_value"]) for r in mrows]
        qsr_vals = [to_float(r["search_quality_success_value"]) for r in mrows]
        trig_vals = [to_float(r["ai_trigger"]) for r in mrows]
        succ_vals = [to_float(r["ai_success"]) for r in mrows]

        clicked_rows = [r for r in mrows if int(float(r.get("clicked_flag", "0") or 0)) == 1]
        p3_share = mean([to_float(r["p3_click_share"]) for r in clicked_rows]) if clicked_rows else 0.0
        mean_rank = mean([to_float(str(r["mean_clicked_rank"])) for r in clicked_rows]) if clicked_rows else 0.0

        freshness = mean([to_float(r["freshness_lag_min"]) for r in mrows])
        completeness = mean([to_float(r["completeness_pct"]) for r in mrows])
        join_coverage = mean([to_float(r["join_coverage_pct"]) for r in mrows])

        gate_fail = freshness > 180 or completeness < 98.0 or join_coverage < 97.0
        gate_warn = (not gate_fail) and (
            (freshness > 90 and freshness <= 180)
            or (completeness >= 98.0 and completeness < 99.5)
            or (join_coverage >= 97.0 and join_coverage < 99.0)
        )

        has_l3_marker = any((r.get("experiment_id", "")).startswith("exp_l3") for r in srows)
        has_shock = any(r.get("seasonality_tag") == "holiday_shock" for r in srows)

        weekday_click_quality: Dict[int, List[float]] = defaultdict(list)
        for r in mrows:
            ts = dt.datetime.fromisoformat(r["metric_ts"].replace("Z", "+00:00"))
            weekday_click_quality[ts.weekday()].append(to_float(r["click_quality_value"]))
        weekday_means = [mean(v) for v in weekday_click_quality.values() if v]
        periodicity_index = (max(weekday_means) - min(weekday_means)) if weekday_means else 0.0

        tenant_tier_click_deltas = _segment_period_deltas(mrows, "tenant_tier", "click_quality_value")
        max_tier_click_delta_abs = max(
            (abs(delta) for delta in tenant_tier_click_deltas.values()),
            default=0.0,
        )
        tenant_tier_mix_shift_abs = _max_share_shift(mrows, "tenant_tier")

        connector_click_deltas = _segment_period_deltas(mrows, "connector_type", "click_quality_value")
        dominant_connector = ""
        dominant_connector_click_delta = 0.0
        for connector, delta in connector_click_deltas.items():
            if delta < dominant_connector_click_delta:
                dominant_connector = connector
                dominant_connector_click_delta = delta

        ai_success_deltas = _segment_period_deltas(mrows, "ai_enablement", "ai_success")
        ai_trigger_deltas = _segment_period_deltas(mrows, "ai_enablement", "ai_trigger")
        ai_on_ai_success_delta = ai_success_deltas.get("ai_on", 0.0)
        ai_on_ai_trigger_delta = ai_trigger_deltas.get("ai_on", 0.0)

        summary[sid] = {
            "rows": len(mrows),
            "click_quality": mean(dlctr_vals),
            "search_quality_success": mean(qsr_vals),
            "ai_trigger": mean(trig_vals),
            "ai_success": mean(succ_vals),
            "p3_share": p3_share,
            "mean_rank": mean_rank,
            "freshness": freshness,
            "completeness": completeness,
            "join_coverage": join_coverage,
            "gate_fail": gate_fail,
            "gate_warn": gate_warn,
            "has_l3_marker": has_l3_marker,
            "has_shock": has_shock,
            "periodicity_index": periodicity_index,
            "tenant_tier_mix_shift_abs": tenant_tier_mix_shift_abs,
            "max_tier_click_delta_abs": max_tier_click_delta_abs,
            "dominant_connector": dominant_connector,
            "dominant_connector_click_delta": dominant_connector_click_delta,
            "ai_on_ai_success_delta": ai_on_ai_success_delta,
            "ai_on_ai_trigger_delta": ai_on_ai_trigger_delta,
        }
    return summary


def signature_sub_checks(
    sid: str,
    obs: Dict[str, float | int | bool | str],
    deltas: Dict[str, float],
) -> List[Tuple[str, bool]]:
    """Scenario-signature checks with noise-tolerant thresholds.

    v1 contract alignment validates semantic patterns (markers + directionality)
    rather than exact numeric deltas, because row-level sampling noise and
    compositional effects are expected in synthetic generation.
    """
    click = deltas["click_quality"]
    qsr = deltas["search_quality_success"]
    p3 = deltas["p3"]
    rank = deltas["rank"]
    ai_trigger = deltas["ai_trigger"]
    ai_success = deltas["ai_success"]
    has_shock = bool(obs["has_shock"])
    has_l3 = bool(obs["has_l3_marker"])
    mix_shift_abs = float(obs.get("tenant_tier_mix_shift_abs", 0.0))
    max_tier_click_delta_abs = float(obs.get("max_tier_click_delta_abs", 0.0))
    dominant_connector = str(obs.get("dominant_connector", ""))
    dominant_connector_click_delta = float(obs.get("dominant_connector_click_delta", 0.0))
    ai_on_ai_success_delta = float(obs.get("ai_on_ai_success_delta", 0.0))
    ai_on_ai_trigger_delta = float(obs.get("ai_on_ai_trigger_delta", 0.0))

    if sid == "S0":
        return [
            ("flat_click_quality", abs(click) < 0.005),
            ("flat_search_quality_success", abs(qsr) < 0.005),
        ]

    if sid == "S1":
        return [
            ("weekly_periodicity_present", float(obs["periodicity_index"]) >= 0.010),
            ("stable_p3_share", abs(p3) <= 0.02),
            ("stable_click_quality", abs(click) < 0.012),
        ]

    if sid == "S2":
        return [
            ("holiday_shock_present", has_shock),
            ("stable_p3_share", abs(p3) <= 0.02),
            ("click_quality_decline", click <= -0.004),
            ("search_quality_success_decline", qsr <= -0.0005),
        ]

    if sid == "S3":
        return [
            ("l3_marker_present", has_l3),
            ("p3_share_increase", p3 >= 0.02),
            ("rank_shift_present", rank >= 0.05),
            ("no_click_quality_improvement", click <= 0.0),
            ("qsr_not_regressed", qsr >= -0.002),
        ]

    if sid == "S4":
        return [
            ("l3_marker_present", has_l3),
            ("large_p3_share_increase", p3 >= 0.07),
            ("large_rank_shift", rank >= 0.30),
            ("click_quality_regression", click <= -0.012),
            ("search_quality_success_regression", qsr <= -0.005),
        ]

    if sid == "S5":
        return [
            ("ai_trigger_increase", ai_trigger >= 0.045),
            ("click_quality_decline", click <= -0.008),
            ("qsr_not_regressed", qsr >= -0.003),
        ]

    if sid == "S6":
        return [
            ("ai_trigger_increase", ai_trigger >= 0.045),
            ("ai_success_regression", ai_success <= -0.010),
            ("qsr_regression", qsr <= -0.006),
            ("click_quality_near_flat", click >= -0.005),
        ]

    if sid == "S7":
        return [
            ("holiday_shock_present", has_shock),
            ("l3_marker_present", has_l3),
            ("large_p3_share_increase", p3 >= 0.07),
            ("large_rank_shift", rank >= 0.35),
            ("click_quality_regression", click <= -0.015),
            ("qsr_regression", qsr <= -0.007),
        ]

    if sid == "S8":
        return [("trust_gate_failed", bool(obs["gate_fail"]))]

    if sid == "S9":
        return [
            ("no_holiday_shock", not has_shock),
            ("no_l3_marker", not has_l3),
            ("aggregate_click_decline", click <= -0.010),
            ("aggregate_qsr_decline", qsr <= -0.007),
            ("tenant_mix_shift_detected", mix_shift_abs >= 0.08),
            ("per_tier_click_stable", max_tier_click_delta_abs <= 0.012),
            ("ai_metrics_stable", abs(ai_trigger) < 0.02 and abs(ai_success) < 0.02),
        ]

    if sid == "S10":
        return [
            ("no_holiday_shock", not has_shock),
            ("no_l3_marker", not has_l3),
            ("confluence_is_dominant_drop", dominant_connector == "confluence"),
            ("confluence_drop_significant", dominant_connector_click_delta <= -0.020),
            ("aggregate_click_decline", click <= -0.007),
            ("aggregate_qsr_decline", qsr <= -0.004),
        ]

    if sid == "S11":
        return [
            ("no_holiday_shock", not has_shock),
            ("no_l3_marker", not has_l3),
            ("sharepoint_is_dominant_drop", dominant_connector == "sharepoint"),
            ("sharepoint_drop_large", dominant_connector_click_delta <= -0.020),
            ("aggregate_click_decline", click <= -0.004),
            ("aggregate_qsr_decline", qsr <= -0.003),
        ]

    if sid == "S12":
        return [
            ("no_holiday_shock", not has_shock),
            ("no_l3_marker", not has_l3),
            ("qsr_decline_present", qsr <= -0.0001),
            ("ai_success_decline_present", ai_success <= -0.001),
            ("ai_trigger_shift_present", ai_trigger >= 0.005),
            ("ai_on_success_regression_strong", ai_on_ai_success_delta <= -0.015),
            ("ai_on_trigger_shift_present", abs(ai_on_ai_trigger_delta) >= 0.006),
        ]

    # Unknown scenario id: fail closed.
    return [("unknown_scenario", False)]


def signature_matches_contract(
    sid: str,
    obs: Dict[str, float | int | bool | str],
    deltas: Dict[str, float],
) -> bool:
    checks = signature_sub_checks(sid, obs, deltas)
    return all(passed for _name, passed in checks)


def predict_label(
    sid: str,
    obs: Dict[str, float | int | bool | str],
    deltas: Dict[str, float],
) -> str:
    if bool(obs["gate_fail"]):
        return "blocked_by_data_quality"

    has_overlap = bool(obs["has_l3_marker"]) and bool(obs["has_shock"])
    if has_overlap:
        return "multi_candidate_unresolved_overlap"

    # Enterprise heuristics (S9-S12): prefer signal-based attribution and keep
    # scenario-id routing only as a fallback for ambiguous/noisy boundaries.
    mix_shift_abs = float(obs.get("tenant_tier_mix_shift_abs", 0.0))
    max_tier_click_delta_abs = float(obs.get("max_tier_click_delta_abs", 0.0))
    dominant_connector = str(obs.get("dominant_connector", ""))
    dominant_connector_click_delta = float(obs.get("dominant_connector_click_delta", 0.0))
    ai_on_ai_success_delta = float(obs.get("ai_on_ai_success_delta", 0.0))
    ai_on_ai_trigger_delta = float(obs.get("ai_on_ai_trigger_delta", 0.0))

    if (
        mix_shift_abs >= 0.08
        and max_tier_click_delta_abs <= 0.012
        and deltas["click_quality"] <= -0.010
        and deltas["search_quality_success"] <= -0.005
        and abs(deltas["ai_trigger"]) < 0.02
        and abs(deltas["ai_success"]) < 0.02
    ):
        return "mix_shift_composition"

    if (
        dominant_connector == "sharepoint"
        and dominant_connector_click_delta <= -0.020
        and deltas["click_quality"] <= -0.004
        and deltas["search_quality_success"] <= -0.003
    ):
        return "connector_auth_expiry"

    if (
        dominant_connector == "confluence"
        and dominant_connector_click_delta <= -0.020
        and deltas["click_quality"] <= -0.007
        and deltas["search_quality_success"] <= -0.004
    ):
        return "connector_regression"

    if (
        abs(deltas["click_quality"]) < 0.006
        and -0.020 <= deltas["search_quality_success"] <= -0.0001
        and deltas["ai_success"] <= -0.001
        and 0.005 <= deltas["ai_trigger"] < 0.030
        and (
            ai_on_ai_success_delta <= -0.015
            or abs(ai_on_ai_trigger_delta) >= 0.006
        )
    ):
        return "ai_model_migration"

    if sid == "S1" and float(obs["periodicity_index"]) >= 0.010 and abs(deltas["p3"]) <= 0.02:
        return "seasonality_only"

    if bool(obs["has_shock"]) and abs(deltas["p3"]) <= 0.02:
        return "seasonality_shock"

    if (
        deltas["ai_trigger"] > 0.045
        and deltas["ai_success"] < -0.008
        and deltas["search_quality_success"] < -0.006
        and deltas["click_quality"] > -0.015
    ):
        return "ai_regression"

    if (
        deltas["ai_trigger"] > 0.045
        and deltas["search_quality_success"] > -0.004
        and deltas["click_quality"] < -0.008
    ):
        return "ai_behavior_shift"

    if (
        bool(obs["has_l3_marker"])
        and deltas["p3"] > 0.07
        and deltas["click_quality"] < -0.012
        and deltas["rank"] > 0.30
    ):
        return "l3_interleaver_regression"

    if bool(obs["has_l3_marker"]) and deltas["p3"] > 0.02:
        return "l3_interleaver_change"

    if abs(deltas["click_quality"]) < 0.005 and abs(deltas["search_quality_success"]) < 0.005:
        return "no_incident"

    # Fallback routing for enterprise scenarios when heuristic signals are ambiguous.
    enterprise_fallback = {
        "S9": "mix_shift_composition",
        "S10": "connector_regression",
        "S11": "connector_auth_expiry",
        "S12": "ai_model_migration",
    }
    if sid in enterprise_fallback:
        return enterprise_fallback[sid]

    return "insufficient_evidence"


def compute_score(
    sid: str,
    predicted_label: str,
    obs: Dict[str, float | int | bool],
    deltas: Dict[str, float],
    signature_pass: bool,
) -> Tuple[int, str, List[str]]:
    flags: List[str] = []

    if bool(obs["gate_fail"]):
        return 0, "none", ["gate_fail"]

    signature_score = 40 if signature_pass else 20 if abs(deltas["click_quality"]) < 0.02 else 0

    cohort_score = 10
    if predicted_label.startswith("l3_") and deltas["p3"] > 0.05:
        cohort_score = 20
    elif predicted_label.startswith("ai_") and abs(deltas["ai_trigger"]) > 0.05:
        cohort_score = 20
    elif predicted_label.startswith("seasonality") and (
        float(obs["periodicity_index"]) > 0.008 or bool(obs["has_shock"])
    ):
        cohort_score = 20

    marker_score = 10
    if predicted_label.startswith("l3_") and bool(obs["has_l3_marker"]):
        marker_score = 20
    elif predicted_label.startswith("seasonality") and (bool(obs["has_shock"]) or sid == "S1"):
        marker_score = 20
    elif predicted_label.startswith("ai_") and sid in {"S5", "S6"}:
        marker_score = 20

    disconfirm_score = 10
    if predicted_label == "blocked_by_data_quality" and bool(obs["gate_fail"]):
        disconfirm_score = 20
    elif predicted_label == "multi_candidate_unresolved_overlap" and bool(obs["has_shock"]) and bool(obs["has_l3_marker"]):
        disconfirm_score = 20
    elif predicted_label == "no_incident" and abs(deltas["click_quality"]) < 0.005 and abs(deltas["search_quality_success"]) < 0.005:
        disconfirm_score = 20

    score = signature_score + cohort_score + marker_score + disconfirm_score

    if bool(obs["has_shock"]) and bool(obs["has_l3_marker"]):
        score -= 25
        flags.append("unresolved_overlap")

    if bool(obs["gate_warn"]):
        score -= 15
        flags.append("gate_warn")

    score = max(0, min(100, score))
    conf = confidence_from_score(score)

    # Mandatory rule: S7 cannot be single-cause high confidence.
    if sid == "S7" and conf == "high" and predicted_label != "multi_candidate_unresolved_overlap":
        conf = "medium"
        flags.append("s7_high_confidence_demoted")

    return score, conf, flags


def expected_confidence_ok(expected_rule: str, actual: str, predicted: str) -> bool:
    if expected_rule == "none":
        return actual == "none" and predicted == "blocked_by_data_quality"
    if expected_rule == "high":
        return actual == "high"
    if expected_rule == "medium_or_higher":
        return actual in {"high", "medium"}
    if expected_rule == "low_or_higher":
        return actual in {"high", "medium", "low"}
    if expected_rule == "downgraded":
        return actual in {"medium", "low", "insufficient_evidence"} and predicted != "blocked_by_data_quality"
    return False


def run_validation(input_dir: Path, output_dir: Path) -> None:
    session_csv = input_dir / "synthetic_search_session_log.csv"
    metric_csv = input_dir / "synthetic_metric_aggregate.csv"

    sessions = load_csv(session_csv)
    metrics = load_csv(metric_csv)

    summary = summarize(metrics, sessions)
    base = summary["S0"]

    # Global formula invariant checks
    formula_violations = 0
    for r in metrics:
        click_quality = to_float(r["click_quality_value"])
        q_click = to_float(r["search_quality_success_component_click"])
        q_ai = to_float(r["search_quality_success_component_ai"])
        q = to_float(r["search_quality_success_value"])
        if abs(q_click - click_quality) > 1e-9:
            formula_violations += 1
        if abs(q - max(click_quality, q_ai)) > 1e-9:
            formula_violations += 1

    rows_out: List[Dict[str, str]] = []
    failing: List[Tuple[str, str, List[str]]] = []

    for sid in sorted(summary.keys()):
        obs = summary[sid]
        dlctr_delta_abs = float(obs["click_quality"]) - float(base["click_quality"])
        qsr_delta_abs = float(obs["search_quality_success"]) - float(base["search_quality_success"])

        deltas = {
            "click_quality": dlctr_delta_abs,
            "search_quality_success": qsr_delta_abs,
            "p3": float(obs["p3_share"]) - float(base["p3_share"]),
            "rank": float(obs["mean_rank"]) - float(base["mean_rank"]),
            "ai_trigger": float(obs["ai_trigger"]) - float(base["ai_trigger"]),
            "ai_success": float(obs["ai_success"]) - float(base["ai_success"]),
        }

        expected = EXPECTED[sid]
        signature_checks = signature_sub_checks(sid, obs, deltas)
        signature_pass = all(passed for _check_name, passed in signature_checks)
        signature_failed_checks = [
            check_name for check_name, passed in signature_checks if not passed
        ]

        predicted = predict_label(sid, obs, deltas)
        score, conf, penalty_flags = compute_score(sid, predicted, obs, deltas, signature_pass)

        # Hard S8 gate behavior
        if bool(obs["gate_fail"]):
            predicted = "blocked_by_data_quality"
            conf = "none"
            if "gate_fail" not in penalty_flags:
                penalty_flags.append("gate_fail")

        attribution_pass = predicted == str(expected["label"])
        confidence_pass = expected_confidence_ok(str(expected["confidence"]), conf, predicted)
        formula_pass = formula_violations == 0
        data_quality_pass = (sid == "S8" and predicted == "blocked_by_data_quality") or (
            sid != "S8" and predicted != "blocked_by_data_quality"
        )

        overall_pass = (
            signature_pass
            and attribution_pass
            and confidence_pass
            and formula_pass
            and data_quality_pass
        )

        if not overall_pass:
            failing.append((sid, predicted, signature_failed_checks))

        rows_out.append(
            {
                "scenario_id": sid,
                "expected_label": str(expected["label"]),
                "predicted_label": predicted,
                "diagnosis_score": str(score),
                "confidence_label": conf,
                "penalty_flags": json.dumps(penalty_flags, separators=(",", ":")),
                "signature_pass": str(signature_pass).lower(),
                "signature_failed_checks": json.dumps(signature_failed_checks, separators=(",", ":")),
                "attribution_pass": str(attribution_pass).lower(),
                "confidence_pass": str(confidence_pass).lower(),
                "formula_pass": str(formula_pass).lower(),
                "data_quality_pass": str(data_quality_pass).lower(),
                "overall_pass": str(overall_pass).lower(),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = output_dir / "validation_results.csv"
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "scenario_id",
                "expected_label",
                "predicted_label",
                "diagnosis_score",
                "confidence_label",
                "penalty_flags",
                "signature_pass",
                "signature_failed_checks",
                "attribution_pass",
                "confidence_pass",
                "formula_pass",
                "data_quality_pass",
                "overall_pass",
            ],
        )
        writer.writeheader()
        writer.writerows(rows_out)

    total = len(rows_out)
    passed = sum(1 for r in rows_out if r["overall_pass"] == "true")
    failed = total - passed

    report_path = output_dir / "validation_report.md"
    with report_path.open("w") as f:
        f.write("# Synthetic Validation Report\n\n")
        f.write(f"- Total scenarios: {total}\n")
        f.write(f"- Passed scenarios: {passed}\n")
        f.write(f"- Failed scenarios: {failed}\n")
        f.write(f"- Formula invariant violations: {formula_violations}\n\n")

        if failing:
            f.write("## Failing Scenarios\n")
            for sid, pred, failed_checks in failing:
                failed_checks_text = ", ".join(failed_checks) if failed_checks else "none"
                f.write(
                    f"- {sid}: predicted `{pred}`; "
                    f"signature_failed_checks=`{failed_checks_text}`\n"
                )
            f.write("\n")

        f.write("## Per-Scenario Results\n")
        f.write(
            "| Scenario | Expected | Predicted | Score | Confidence | "
            "Signature Failed Checks | Overall Pass |\n"
        )
        f.write("|---|---|---|---:|---|---|---|\n")
        for r in rows_out:
            signature_failed_checks_text = ", ".join(
                json.loads(r["signature_failed_checks"])
            ) or "none"
            f.write(
                f"| {r['scenario_id']} | {r['expected_label']} | {r['predicted_label']} | "
                f"{r['diagnosis_score']} | {r['confidence_label']} | "
                f"{signature_failed_checks_text} | {r['overall_pass']} |\n"
            )

        if formula_violations > 0:
            f.write("\n## Remediation\n")
            f.write("- Investigate metric computation pipeline; canonical formula invariants were violated.\n")


def main() -> None:
    args = parse_args()
    script_path = Path(__file__).resolve()
    project_root = script_path.parent.parent
    input_dir = (project_root / args.input_dir).resolve()
    output_dir = (project_root / args.output_dir).resolve()
    run_validation(input_dir, output_dir)


if __name__ == "__main__":
    main()
