#!/usr/bin/env python3
"""Eval stress-test: run the full diagnostic pipeline on eval scenarios.

This script:
1. Loads synthetic data (already generated)
2. Filters to each eval scenario (S4, S5, S7, S8, S9, S0)
3. Runs the FULL pipeline: decompose -> anomaly -> diagnose -> format
4. Scores each run using the eval framework
5. Prints a scorecard

Usage:
    python eval/run_stress_test.py
"""

import csv
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

# ── Setup paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.decompose import run_decomposition
from tools.anomaly import detect_step_change, match_co_movement_pattern, check_data_quality
from tools.diagnose import run_diagnosis
from tools.formatter import format_diagnosis_output
from eval.run_eval import load_scoring_specs, run_three_run_majority


# ── Config ────────────────────────────────────────────────────────────────
SYNTHETIC_METRICS_CSV = PROJECT_ROOT / "data" / "synthetic" / "synthetic_metric_aggregate.csv"

# Map scenario IDs to the eval case spec filenames (in order)
EVAL_CASES = [
    {"scenario_id": "S4", "spec_file": "case1_single_cause.yaml",     "label": "Ranking regression"},
    {"scenario_id": "S5", "spec_file": "case2_ai_adoption_trap.yaml", "label": "AI adoption trap"},
    {"scenario_id": "S7", "spec_file": "case3_multi_cause.yaml",      "label": "Multi-cause overlap"},
    {"scenario_id": "S8", "spec_file": "case6_data_quality_gate.yaml", "label": "Data quality gate block"},
    {"scenario_id": "S9", "spec_file": "case4_mix_shift.yaml",        "label": "Mix-shift"},
    {"scenario_id": "S0", "spec_file": "case5_false_alarm.yaml",      "label": "False alarm (stable)"},
]

# Dimensions relevant for Enterprise Search analysis
ENTERPRISE_DIMENSIONS = ["tenant_tier", "ai_enablement", "connector_type"]

# Metrics to check for co-movement patterns
CO_MOVEMENT_METRICS = ["click_quality_value", "search_quality_success_value", "ai_trigger", "ai_success"]


def build_stress_artifact(results: list[dict]) -> dict:
    """Build a machine-readable artifact for CI diffing and regression checks."""
    total_cases = len(results)
    green_count = sum(1 for r in results if r.get("grade") == "GREEN")
    yellow_count = sum(1 for r in results if r.get("grade") == "YELLOW")
    red_count = sum(1 for r in results if r.get("grade") == "RED")
    error_count = sum(1 for r in results if r.get("grade") == "ERROR")

    scores = [float(r.get("score", 0)) for r in results if "error" not in r]

    artifact_cases = []
    for row in results:
        violations = row.get("violations", [])
        artifact_cases.append(
            {
                "case": row.get("case"),
                "label": row.get("label"),
                "grade": row.get("grade"),
                "score": row.get("score"),
                "run_scores": row.get("run_scores", []),
                "run_grades": row.get("run_grades", []),
                "majority": row.get("majority", {}),
                "decision_status": row.get("decision_status"),
                "severity": row.get("severity"),
                "confidence": row.get("confidence"),
                "violation_rules": [
                    v.get("rule") if isinstance(v, dict) else str(v)
                    for v in violations
                ],
            }
        )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_cases": total_cases,
            "green": green_count,
            "yellow": yellow_count,
            "red": red_count,
            "error": error_count,
            "avg_score": (sum(scores) / len(scores)) if scores else 0.0,
            "min_score": min(scores) if scores else 0.0,
            "max_score": max(scores) if scores else 0.0,
        },
        "cases": artifact_cases,
    }


def _write_stress_artifact(path: Path, artifact: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(artifact, f, indent=2, sort_keys=True)
        f.write("\n")


def load_synthetic_data() -> list[dict]:
    """Load synthetic metric aggregate CSV into a list of dicts."""
    with open(SYNTHETIC_METRICS_CSV, "r") as f:
        reader = csv.DictReader(f)
        return list(reader)


def filter_scenario(rows: list[dict], scenario_id: str) -> list[dict]:
    """Filter rows to a specific scenario."""
    return [r for r in rows if r.get("scenario_id") == scenario_id]


def compute_daily_values(rows: list[dict], metric: str, period: str) -> list[float]:
    """Compute daily averages for a metric in a given period.

    Groups rows by day (using metric_ts date) and computes the mean.
    Returns a list of daily averages in chronological order.
    """
    from collections import defaultdict

    daily = defaultdict(list)
    for row in rows:
        if row.get("period") != period:
            continue
        ts = row.get("metric_ts", "")
        day = ts[:10] if len(ts) >= 10 else ts  # extract YYYY-MM-DD
        val = float(row.get(metric, 0))
        daily[day].append(val)

    # Sort by day and compute averages
    result = []
    for day in sorted(daily.keys()):
        vals = daily[day]
        result.append(sum(vals) / len(vals) if vals else 0.0)

    return result


# Per-metric weekly standard deviations from metric_definitions.yaml.
# Used to set context-aware "stable" thresholds — a 2% ai_trigger change
# is within normal noise, but a 2% Click Quality change is a real signal.
# The threshold is 1.5x the weekly_std as a fraction of the mean.
# WHY 1.5x: Below 1 std is clearly noise, above 2 std is clearly real.
# 1.5x is the boundary — movements smaller than this are "stable."
METRIC_NOISE_THRESHOLDS = {
    "click_quality_value":   0.04,   # weekly_std/mean = 0.015/0.280 = 5.4%; use 4% as threshold
    "search_quality_success_value":     0.03,   # weekly_std/mean = 0.012/0.378 = 3.2%; use 3% as threshold
    "ai_trigger":  0.06,   # weekly_std/mean = 4.5%; was 7% → now 6% (1.3x CV)
    "ai_success":  0.06,   # weekly_std/mean = 2.4%; was 7% → now 6% (2.5x CV)
}
# Default threshold for metrics not in the table
DEFAULT_NOISE_THRESHOLD = 0.03


def compute_metric_direction(rows: list[dict], metric: str) -> str:
    """Determine if a metric went up, down, or stayed stable between periods.

    Uses a per-metric noise threshold derived from the metric's weekly standard
    deviation. This prevents small fluctuations (noise) from being classified
    as real movements.

    WHY per-metric thresholds: AI Answer metrics are noisier than Click Quality/Search Quality Success.
    A 3% ai_trigger change is well within 1 standard deviation of normal
    variation, but a 3% Click Quality change is a meaningful signal. A single fixed
    threshold (like 0.5%) incorrectly classifies AI Answer noise as real movement,
    which breaks co-movement pattern matching.
    """
    baseline_vals = [float(r.get(metric, 0)) for r in rows if r.get("period") == "baseline"]
    current_vals = [float(r.get(metric, 0)) for r in rows if r.get("period") == "current"]

    if not baseline_vals or not current_vals:
        return "stable"

    baseline_mean = sum(baseline_vals) / len(baseline_vals)
    current_mean = sum(current_vals) / len(current_vals)

    if baseline_mean == 0:
        return "stable"

    relative_change = (current_mean - baseline_mean) / abs(baseline_mean)

    # Use per-metric threshold to determine if the change is real or noise
    threshold = METRIC_NOISE_THRESHOLDS.get(metric, DEFAULT_NOISE_THRESHOLD)

    if relative_change > threshold:
        return "up"
    elif relative_change < -threshold:
        return "down"
    else:
        return "stable"


def run_pipeline_for_scenario(rows: list[dict], scenario_id: str) -> tuple[dict, dict]:
    """Run the full diagnostic pipeline on a single scenario's data.

    Pipeline: decompose -> anomaly (step-change + co-movement) -> diagnose -> format

    Returns:
        (diagnosis_dict, formatted_dict)
    """
    print(f"\n{'='*60}")
    print(f"  Running pipeline for scenario {scenario_id}")
    print(f"{'='*60}")

    scenario_rows = filter_scenario(rows, scenario_id)
    print(f"  Filtered {len(scenario_rows)} rows for {scenario_id}")

    if not scenario_rows:
        raise ValueError(f"No rows found for scenario {scenario_id}")

    # ── Step 1: Decomposition ──
    print("  [1/4] Running decomposition...")
    decomposition = run_decomposition(
        rows=scenario_rows,
        metric_field="click_quality_value",
        dimensions=ENTERPRISE_DIMENSIONS,
    )
    print(f"        Aggregate delta: {decomposition['aggregate']['absolute_delta']:.4f}")
    print(f"        Relative delta: {decomposition['aggregate']['relative_delta_pct']:.2f}%")
    print(f"        Severity: {decomposition['aggregate']['severity']}")
    mix_pct = decomposition['mix_shift'].get('mix_shift_contribution_pct', 0.0)
    print(f"        Mix-shift contribution: {mix_pct:.1f}%")

    # ── Step 2: Anomaly detection ──
    print("  [2/4] Running anomaly detection...")

    # 2a: Step-change detection on the "current" period daily values
    daily_click_quality = compute_daily_values(scenario_rows, "click_quality_value", "current")
    step_change = detect_step_change(daily_click_quality)
    print(f"        Step-change detected: {step_change['detected']}")

    # 2b: Co-movement pattern matching across key metrics
    co_movement_observed = {}
    for metric in CO_MOVEMENT_METRICS:
        direction = compute_metric_direction(scenario_rows, metric)
        co_movement_observed[metric.replace("_value", "")] = direction

    # Map to expected keys for co-movement table
    observed_for_table = {
        "click_quality": co_movement_observed.get("click_quality", "stable"),
        "search_quality_success": co_movement_observed.get("search_quality_success", "stable"),
        "ai_trigger": co_movement_observed.get("ai_trigger", "stable"),
        "ai_success": co_movement_observed.get("ai_success", "stable"),
    }
    co_movement = match_co_movement_pattern(observed_for_table)
    print(f"        Co-movement pattern: {co_movement.get('likely_cause', 'no match')}")
    print(f"        Is positive signal: {co_movement.get('is_positive', False)}")

    # 2c: Data quality check
    dq_rows = []
    for r in scenario_rows:
        dq_rows.append({
            "data_completeness": float(r.get("completeness_pct", 100)) / 100.0,
            "data_freshness_min": float(r.get("freshness_lag_min", 0)),
        })
    dq_result = check_data_quality(dq_rows)
    print(f"        Data quality: {dq_result['status']}")

    # ── Step 3: Diagnosis ──
    # Pass co-movement results so archetype recognition can work.
    # This is the key v1.1 fix: co-movement drives archetype selection
    # which in turn controls severity, hypothesis framing, and action items.
    print("  [3/4] Running diagnosis...")
    diagnosis = run_diagnosis(
        decomposition=decomposition,
        step_change_result=step_change,
        co_movement_result=co_movement,
        trust_gate_result=dq_result,
    )
    print(f"        Hypothesis: {diagnosis['primary_hypothesis']['description'][:80]}...")
    print(f"        Confidence: {diagnosis['confidence']['level']}")
    print(f"        Decision status: {diagnosis.get('decision_status', 'diagnosed')}")
    print(f"        Category: {diagnosis['primary_hypothesis'].get('category', 'N/A')}")

    # ── Step 4: Formatting ──
    print("  [4/4] Running formatter...")
    formatted = format_diagnosis_output(diagnosis)
    slack_lines = [l for l in formatted['slack_message'].split('\n') if l.strip()]
    print(f"        Slack message: {len(slack_lines)} lines")
    report_lines = formatted['short_report'].split('\n')
    print(f"        Report: {len(report_lines)} lines")

    return diagnosis, formatted


def run_eval(artifact_json: Path | None = None):
    """Run the full eval stress-test across configured scenarios."""
    print("=" * 60)
    print("  SEARCH METRIC ANALYZER — EVAL STRESS TEST")
    print("=" * 60)

    # Load data
    print("\nLoading synthetic data...")
    all_rows = load_synthetic_data()
    print(f"Loaded {len(all_rows)} total rows")

    # Load scoring specs
    specs = load_scoring_specs()
    spec_by_file = {s.get("_source_file", ""): s for s in specs}
    print(f"Loaded {len(specs)} scoring specs")

    # Run each eval case
    results = []

    for case in EVAL_CASES:
        sid = case["scenario_id"]
        spec_file = case["spec_file"]
        label = case["label"]

        # Find the matching spec
        spec = None
        for s in specs:
            source = s.get("_source_file", "")
            if spec_file in source:
                spec = s
                break

        if spec is None:
            print(f"\n  WARNING: No spec found for {spec_file}, skipping {sid}")
            continue

        try:
            # Run the pipeline
            diagnosis, formatted = run_pipeline_for_scenario(all_rows, sid)

            # Score with 3-run majority verdict
            run_pack = run_three_run_majority(
                spec=spec,
                diagnosis=diagnosis,
                formatted=formatted,
                runs=3,
            )
            score_result = run_pack["majority"]
            first_run = run_pack["run_results"][0]
            run_scores = [r["total_score"] for r in run_pack["run_results"]]
            run_grades = [r["grade"] for r in run_pack["run_results"]]

            results.append({
                "case": sid,
                "label": label,
                "score": round(score_result["avg_score"], 1),
                "grade": score_result["verdict"],
                "raw_score": first_run["raw_score"],
                "deductions": first_run["deductions"],
                "violations": first_run.get("violations", []),
                "per_dimension": first_run.get("per_dimension", {}),
                "run_scores": run_scores,
                "run_grades": run_grades,
                "majority": score_result,
                "hypothesis": diagnosis["primary_hypothesis"]["description"],
                "decision_status": diagnosis.get("decision_status", "diagnosed"),
                "confidence": diagnosis["confidence"]["level"],
                "severity": diagnosis["aggregate"]["severity"],
                "spec": spec,
            })

            print(
                f"\n  RUN SCORES: {run_scores} / {run_grades} "
                f"-> MAJORITY {score_result['verdict']} "
                f"(avg {score_result['avg_score']:.1f})"
            )
            if first_run.get("violations"):
                print(f"  VIOLATIONS (first run): {first_run['violations']}")

        except Exception as e:
            print(f"\n  ERROR running {sid}: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                "case": sid,
                "label": label,
                "score": 0,
                "grade": "ERROR",
                "error": str(e),
            })

    # ── Print Scorecard ──────────────────────────────────────────────────
    print("\n\n")
    print("=" * 80)
    print("  SCORECARD")
    print("=" * 80)
    print()
    print(f"{'Case':<6} {'Scenario':<30} {'Score':<8} {'Grade':<8} {'Root Cause Found?':<25} {'Violations'}")
    print("-" * 110)

    for r in results:
        violations_list = r.get("violations", [])
        if violations_list:
            violations_str = ", ".join(v["rule"] if isinstance(v, dict) else str(v) for v in violations_list)
        else:
            violations_str = "None"
        root_cause = "ERROR" if "error" in r else r.get("hypothesis", "")[:24]
        print(f"{r['case']:<6} {r['label']:<30} {r['score']:<8} {r['grade']:<8} {root_cause:<25} {violations_str}")

    # ── Detailed per-dimension breakdown ──
    print("\n\n")
    print("=" * 80)
    print("  PER-DIMENSION BREAKDOWN")
    print("=" * 80)

    for r in results:
        if "error" in r:
            continue
        print(f"\n  {r['case']} — {r['label']} (Total: {r['score']}/{100})")
        print(f"  Hypothesis: {r['hypothesis'][:100]}")
        print(f"  Decision status: {r.get('decision_status', 'diagnosed')}")
        print(f"  Confidence: {r['confidence']}, Severity: {r.get('severity', 'N/A')}")
        print(f"  Run grades: {r.get('run_grades', [])}")
        print(f"  Run scores: {r.get('run_scores', [])}")
        per_dim = r.get("per_dimension", {})
        for dim_name, dim_info in per_dim.items():
            score = dim_info.get("earned", 0)
            max_pts = dim_info.get("max", "?")
            print(f"    {dim_name:<30} {score}/{max_pts}")
            # Print scoring details
            for detail in dim_info.get("details", []):
                print(f"      {detail}")
        if r.get("deductions", 0) > 0:
            print(f"    {'DEDUCTIONS':<30} -{r['deductions']}")
        if r.get("violations"):
            print(f"    Violations: {r['violations']}")

    # ── Summary stats ──
    print("\n\n")
    print("=" * 80)
    print("  SUMMARY")
    print("=" * 80)

    green_count = sum(1 for r in results if r.get("grade") == "GREEN")
    yellow_count = sum(1 for r in results if r.get("grade") == "YELLOW")
    red_count = sum(1 for r in results if r.get("grade") == "RED")
    error_count = sum(1 for r in results if r.get("grade") == "ERROR")

    total_cases = len(results)
    print(f"  GREEN:  {green_count}/{total_cases}")
    print(f"  YELLOW: {yellow_count}/{total_cases}")
    print(f"  RED:    {red_count}/{total_cases}")
    if error_count:
        print(f"  ERROR:  {error_count}/{total_cases}")

    scores = [r["score"] for r in results if "error" not in r]
    if scores:
        print(f"\n  Average score: {sum(scores)/len(scores):.1f}/100")
        print(f"  Min score:     {min(scores)}/100")
        print(f"  Max score:     {max(scores)}/100")

    # ── Print full diagnosis details for any RED/YELLOW cases ──
    problem_cases = [r for r in results if r.get("grade") in ("RED", "YELLOW", "ERROR")]
    if problem_cases:
        print("\n\n")
        print("=" * 80)
        print("  DETAILED ANALYSIS OF RED/YELLOW CASES")
        print("=" * 80)

        for r in problem_cases:
            print(f"\n  --- {r['case']} ({r['label']}) — Grade: {r['grade']} ---")
            if "error" in r:
                print(f"  Error: {r['error']}")
                continue

            print(f"  Full hypothesis: {r['hypothesis']}")
            print(f"  Confidence: {r['confidence']}")
            print(f"  Severity: {r.get('severity', 'N/A')}")

            # What the spec expected
            spec = r.get("spec", {})
            must_find = spec.get("must_find_root_cause", "N/A")
            print(f"  Expected root cause: {must_find}")

            # What went wrong in each dimension
            per_dim = r.get("per_dimension", {})
            for dim_name, dim_info in per_dim.items():
                score = dim_info.get("earned", 0)
                max_pts = dim_info.get("max", "?")
                if isinstance(max_pts, (int, float)) and score < max_pts:
                    print(f"  Lost points in {dim_name}: {score}/{max_pts}")
                    for detail in dim_info.get("details", []):
                        if detail.startswith("+0"):
                            print(f"    {detail}")

            if r.get("violations"):
                print(f"  Violations that cost points: {r['violations']}")

    if artifact_json is not None:
        artifact = build_stress_artifact(results)
        _write_stress_artifact(artifact_json, artifact)
        print(f"\n  Wrote machine-readable artifact: {artifact_json}")

    # Return results for further analysis
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run stress eval pipeline")
    parser.add_argument(
        "--artifact-json",
        default=None,
        help="Optional path to write machine-readable stress results JSON",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    artifact_path = Path(args.artifact_json) if args.artifact_json else None
    results = run_eval(artifact_json=artifact_path)
