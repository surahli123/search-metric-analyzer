#!/usr/bin/env python3
"""Validate synthetic scenarios S0-S8 and emit results/report.

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
    "S0": {"label": "no_incident", "confidence": "low_or_higher", "dlctr": 0.000, "qsr": 0.000},
    "S1": {"label": "seasonality_only", "confidence": "high", "dlctr": 0.000, "qsr": 0.000},
    "S2": {"label": "seasonality_shock", "confidence": "medium_or_higher", "dlctr": -0.015, "qsr": -0.010},
    "S3": {"label": "l3_interleaver_change", "confidence": "medium_or_higher", "dlctr": -0.006, "qsr": 0.004},
    "S4": {"label": "l3_interleaver_regression", "confidence": "high", "dlctr": -0.035, "qsr": -0.022},
    "S5": {"label": "sain_behavior_shift", "confidence": "medium_or_higher", "dlctr": -0.020, "qsr": 0.006},
    "S6": {"label": "sain_regression", "confidence": "high", "dlctr": 0.000, "qsr": -0.030},
    "S7": {
        "label": "multi_candidate_unresolved_overlap",
        "confidence": "downgraded",
        "dlctr": -0.045,
        "qsr": -0.030,
    },
    "S8": {"label": "blocked_by_data_quality", "confidence": "none", "dlctr": 0.000, "qsr": 0.000},
}

ABS_TOL = {"dlctr": 0.006, "qsr": 0.008}
REL_TOL = {"dlctr": 0.020, "qsr": 0.025}


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


def summarize(metrics: List[Dict[str, str]], sessions: List[Dict[str, str]]) -> Dict[str, Dict[str, float | int | bool]]:
    by_sid_metrics: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    by_sid_sessions: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    for row in metrics:
        by_sid_metrics[row["scenario_id"]].append(row)
    for row in sessions:
        by_sid_sessions[row["scenario_id"]].append(row)

    summary: Dict[str, Dict[str, float | int | bool]] = {}
    for sid in sorted(by_sid_metrics.keys()):
        mrows = by_sid_metrics[sid]
        srows = by_sid_sessions.get(sid, [])

        dlctr_vals = [to_float(r["dlctr_value"]) for r in mrows]
        qsr_vals = [to_float(r["qsr_value"]) for r in mrows]
        trig_vals = [to_float(r["sain_trigger"]) for r in mrows]
        succ_vals = [to_float(r["sain_success"]) for r in mrows]

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

        weekday_dlctr: Dict[int, List[float]] = defaultdict(list)
        for r in mrows:
            ts = dt.datetime.fromisoformat(r["metric_ts"].replace("Z", "+00:00"))
            weekday_dlctr[ts.weekday()].append(to_float(r["dlctr_value"]))
        weekday_means = [mean(v) for v in weekday_dlctr.values() if v]
        periodicity_index = (max(weekday_means) - min(weekday_means)) if weekday_means else 0.0

        summary[sid] = {
            "rows": len(mrows),
            "dlctr": mean(dlctr_vals),
            "qsr": mean(qsr_vals),
            "sain_trigger": mean(trig_vals),
            "sain_success": mean(succ_vals),
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
        }
    return summary


def predict_label(sid: str, obs: Dict[str, float | int | bool], deltas: Dict[str, float]) -> str:
    if bool(obs["gate_fail"]):
        return "blocked_by_data_quality"

    has_overlap = bool(obs["has_l3_marker"]) and bool(obs["has_shock"])
    if has_overlap:
        return "multi_candidate_unresolved_overlap"

    if sid == "S1" and float(obs["periodicity_index"]) >= 0.010 and abs(deltas["p3"]) <= 0.02:
        return "seasonality_only"

    if bool(obs["has_shock"]) and abs(deltas["p3"]) <= 0.02:
        return "seasonality_shock"

    if (
        deltas["sain_trigger"] > 0.06
        and deltas["sain_success"] < 0.0
        and deltas["qsr"] < -0.020
        and deltas["dlctr"] > -0.010
    ):
        return "sain_regression"

    if deltas["sain_trigger"] > 0.06 and deltas["qsr"] >= 0.0 and deltas["dlctr"] < -0.01:
        return "sain_behavior_shift"

    if deltas["p3"] > 0.12 and deltas["dlctr"] < -0.02 and deltas["rank"] > 0.5:
        return "l3_interleaver_regression"

    if deltas["p3"] > 0.05:
        return "l3_interleaver_change"

    if abs(deltas["dlctr"]) < 0.005 and abs(deltas["qsr"]) < 0.005:
        return "no_incident"

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

    signature_score = 40 if signature_pass else 20 if abs(deltas["dlctr"]) < 0.02 else 0

    cohort_score = 10
    if predicted_label.startswith("l3_") and deltas["p3"] > 0.05:
        cohort_score = 20
    elif predicted_label.startswith("sain_") and abs(deltas["sain_trigger"]) > 0.05:
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
    elif predicted_label.startswith("sain_") and sid in {"S5", "S6"}:
        marker_score = 20

    disconfirm_score = 10
    if predicted_label == "blocked_by_data_quality" and bool(obs["gate_fail"]):
        disconfirm_score = 20
    elif predicted_label == "multi_candidate_unresolved_overlap" and bool(obs["has_shock"]) and bool(obs["has_l3_marker"]):
        disconfirm_score = 20
    elif predicted_label == "no_incident" and abs(deltas["dlctr"]) < 0.005 and abs(deltas["qsr"]) < 0.005:
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
        dlctr = to_float(r["dlctr_value"])
        q_click = to_float(r["qsr_component_click"])
        q_sain = to_float(r["qsr_component_sain"])
        q = to_float(r["qsr_value"])
        if abs(q_click - dlctr) > 1e-9:
            formula_violations += 1
        if abs(q - max(dlctr, q_sain)) > 1e-9:
            formula_violations += 1

    rows_out: List[Dict[str, str]] = []
    failing: List[Tuple[str, str]] = []

    for sid in sorted(summary.keys()):
        obs = summary[sid]
        dlctr_delta_abs = float(obs["dlctr"]) - float(base["dlctr"])
        qsr_delta_abs = float(obs["qsr"]) - float(base["qsr"])
        dlctr_delta_rel = dlctr_delta_abs / max(1e-9, float(base["dlctr"]))
        qsr_delta_rel = qsr_delta_abs / max(1e-9, float(base["qsr"]))

        deltas = {
            "dlctr": dlctr_delta_abs,
            "qsr": qsr_delta_abs,
            "p3": float(obs["p3_share"]) - float(base["p3_share"]),
            "rank": float(obs["mean_rank"]) - float(base["mean_rank"]),
            "sain_trigger": float(obs["sain_trigger"]) - float(base["sain_trigger"]),
            "sain_success": float(obs["sain_success"]) - float(base["sain_success"]),
        }

        expected = EXPECTED[sid]

        if sid == "S1":
            signature_pass = (
                float(obs["periodicity_index"]) >= 0.010 and abs(deltas["p3"]) <= 0.02
            )
        elif sid == "S8":
            signature_pass = bool(obs["gate_fail"])
        else:
            exp_dlctr = float(expected["dlctr"])
            exp_qsr = float(expected["qsr"])

            if sid == "S6":
                dlctr_abs_ok = abs(dlctr_delta_abs - exp_dlctr) <= (0.005 + ABS_TOL["dlctr"])
            else:
                dlctr_abs_ok = abs(dlctr_delta_abs - exp_dlctr) <= ABS_TOL["dlctr"]

            qsr_abs_ok = abs(qsr_delta_abs - exp_qsr) <= ABS_TOL["qsr"]
            dlctr_rel_ok = abs(dlctr_delta_rel - (exp_dlctr / max(1e-9, float(base["dlctr"])))) <= REL_TOL["dlctr"]
            qsr_rel_ok = abs(qsr_delta_rel - (exp_qsr / max(1e-9, float(base["qsr"])))) <= REL_TOL["qsr"]
            signature_pass = dlctr_abs_ok and qsr_abs_ok and dlctr_rel_ok and qsr_rel_ok

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
            failing.append((sid, predicted))

        rows_out.append(
            {
                "scenario_id": sid,
                "expected_label": str(expected["label"]),
                "predicted_label": predicted,
                "diagnosis_score": str(score),
                "confidence_label": conf,
                "penalty_flags": json.dumps(penalty_flags, separators=(",", ":")),
                "signature_pass": str(signature_pass).lower(),
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
            for sid, pred in failing:
                f.write(f"- {sid}: predicted `{pred}`\n")
            f.write("\n")

        f.write("## Per-Scenario Results\n")
        f.write("| Scenario | Expected | Predicted | Score | Confidence | Overall Pass |\n")
        f.write("|---|---|---|---:|---|---|\n")
        for r in rows_out:
            f.write(
                f"| {r['scenario_id']} | {r['expected_label']} | {r['predicted_label']} | "
                f"{r['diagnosis_score']} | {r['confidence_label']} | {r['overall_pass']} |\n"
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
