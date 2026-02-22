#!/usr/bin/env python3
"""Anomaly detection tool for Enterprise Search metrics.

This module provides four diagnostic functions used in the metric diagnosis workflow:
1. check_data_quality   — Gate check: is the data trustworthy before we diagnose?
2. detect_step_change   — Did a metric jump overnight (step-change vs gradual drift)?
3. match_co_movement_pattern — Which known failure mode matches the observed metric
                               directions? Uses the co-movement diagnostic table from
                               metric_definitions.yaml.
4. check_against_baseline    — Is a metric value within its expected range (z-score)?

Design philosophy:
- Each function is a pure diagnostic step — takes data in, returns a dict out.
- The CLI mode wraps these for Claude Code to call as shell commands.
- All output is JSON to stdout so Claude Code can parse it programmatically.

Usage (CLI):
    python tools/anomaly.py --input data.csv --metric dlctr_value

Usage (import):
    from tools.anomaly import check_data_quality, detect_step_change
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants — thresholds come from the diagnostic workflow design
# ---------------------------------------------------------------------------

# Data quality gate thresholds (from PRD: completeness >= 96%, freshness <= 60 min)
COMPLETENESS_FAIL_THRESHOLD = 0.96   # Below this = fail, data is unreliable
COMPLETENESS_WARN_THRESHOLD = 0.98   # Below this but above fail = warning
FRESHNESS_FAIL_THRESHOLD = 60        # Minutes; above this = stale data
FRESHNESS_WARN_THRESHOLD = 30        # Minutes; above this but below fail = warning

# Z-score threshold for baseline comparison
# 2.0 standard deviations is a common choice — catches ~95% of normal variation
ZSCORE_ANOMALY_THRESHOLD = 2.0


# ---------------------------------------------------------------------------
# Helper: Load co-movement diagnostic table from YAML
# ---------------------------------------------------------------------------

def _load_co_movement_table() -> List[Dict[str, Any]]:
    """Load the co-movement diagnostic table from metric_definitions.yaml.

    We load from YAML at call time (not import time) to avoid breaking imports
    if the file is missing — tests that don't need the table still work.

    Returns a list of pattern dicts, each with:
        - pattern: {dlctr: "down", qsr: "down", ...}
        - likely_cause: str
        - description: str
        - priority_hypotheses: list
        - is_positive: bool (optional, defaults False)
    """
    # PyYAML is our only non-stdlib dependency (listed in requirements.txt)
    import yaml

    # Resolve path relative to this file's location, not cwd.
    # tools/anomaly.py -> project_root/data/knowledge/metric_definitions.yaml
    project_root = Path(__file__).resolve().parent.parent
    yaml_path = project_root / "data" / "knowledge" / "metric_definitions.yaml"

    with open(yaml_path, "r") as f:
        definitions = yaml.safe_load(f)

    return definitions.get("co_movement_diagnostic_table", [])


# ---------------------------------------------------------------------------
# Function 1: Data Quality Gate
# ---------------------------------------------------------------------------

def check_data_quality(rows: List[Dict[str, float]]) -> Dict[str, Any]:
    """Check if the data is reliable enough to diagnose.

    This is Step 1 of the diagnostic workflow — if data quality is bad,
    any metric movement could be a logging artifact, not a real change.
    We check BEFORE running any analysis to avoid chasing ghosts.

    Args:
        rows: List of dicts, each with 'data_completeness' (0-1 ratio)
              and 'data_freshness_min' (minutes since last update).

    Returns:
        {"status": "pass"|"fail"|"warn", "reason": str,
         "avg_completeness": float, "avg_freshness_min": float}
    """
    if not rows:
        return {
            "status": "fail",
            "reason": "No data rows provided",
            "avg_completeness": 0.0,
            "avg_freshness_min": 0.0,
        }

    # Compute averages across all rows — a single bad row shouldn't fail
    # the gate, but systemic issues (avg below threshold) should.
    # Use .get() with defaults to handle rows missing these fields gracefully
    avg_completeness = sum(r.get("data_completeness", 0.0) for r in rows) / len(rows)
    avg_freshness = sum(r.get("data_freshness_min", 0.0) for r in rows) / len(rows)

    # Check hard failure thresholds first (order matters: fail > warn > pass)
    if avg_completeness < COMPLETENESS_FAIL_THRESHOLD:
        return {
            "status": "fail",
            "reason": (
                f"Data completeness too low: {avg_completeness:.3f} "
                f"(threshold: {COMPLETENESS_FAIL_THRESHOLD})"
            ),
            "avg_completeness": avg_completeness,
            "avg_freshness_min": avg_freshness,
        }

    if avg_freshness > FRESHNESS_FAIL_THRESHOLD:
        return {
            "status": "fail",
            "reason": (
                f"Data freshness too stale: {avg_freshness:.1f} min "
                f"(threshold: {FRESHNESS_FAIL_THRESHOLD} min)"
            ),
            "avg_completeness": avg_completeness,
            "avg_freshness_min": avg_freshness,
        }

    # Check warning thresholds — borderline data, proceed with caution
    warnings: List[str] = []
    if avg_completeness < COMPLETENESS_WARN_THRESHOLD:
        warnings.append(
            f"completeness borderline: {avg_completeness:.3f}"
        )
    if avg_freshness > FRESHNESS_WARN_THRESHOLD:
        warnings.append(
            f"freshness borderline: {avg_freshness:.1f} min"
        )

    if warnings:
        return {
            "status": "warn",
            "reason": "; ".join(warnings),
            "avg_completeness": avg_completeness,
            "avg_freshness_min": avg_freshness,
        }

    # All clear — data is trustworthy
    return {
        "status": "pass",
        "reason": "Data quality checks passed",
        "avg_completeness": avg_completeness,
        "avg_freshness_min": avg_freshness,
    }


# ---------------------------------------------------------------------------
# Function 2: Step-Change Detection
# ---------------------------------------------------------------------------

def detect_step_change(
    daily_values: List[float],
    threshold_pct: float = 2.0,
) -> Dict[str, Any]:
    """Detect overnight step-changes in a daily metric time series.

    A step-change is a sudden, sustained shift — the metric drops (or jumps)
    between one day and the next, and STAYS at the new level. This is the
    hallmark of a code deploy, experiment ramp, or config change.

    Contrast with gradual drift (each day slightly lower), which suggests
    seasonal or behavioral causes.

    Algorithm:
    - For each consecutive pair of days, compute the percent change.
    - If any single day-over-day change exceeds the threshold AND the metric
      stays near the new level afterward, flag it as a step-change.
    - We use the magnitude of the largest single-day jump to decide.

    Args:
        daily_values: List of daily metric averages, ordered chronologically.
        threshold_pct: Minimum percent change to consider a step-change (e.g., 2.0 = 2%).

    Returns:
        {"detected": bool, "change_day_index": int|None, "magnitude_pct": float}
    """
    if len(daily_values) < 2:
        return {"detected": False, "change_day_index": None, "magnitude_pct": 0.0}

    # Find the largest single day-over-day percent change
    max_change_pct = 0.0
    max_change_idx = None

    for i in range(1, len(daily_values)):
        prev = daily_values[i - 1]
        curr = daily_values[i]

        # Guard against division by zero (shouldn't happen with real metrics)
        if abs(prev) < 1e-12:
            continue

        # Percent change: negative means drop, positive means increase
        change_pct = abs((curr - prev) / prev) * 100.0

        if change_pct > max_change_pct:
            max_change_pct = change_pct
            max_change_idx = i

    # A step-change must exceed the threshold AND be the dominant movement.
    # "Dominant" means this single jump accounts for most of the total change.
    # This distinguishes a step from a gradual slope.
    if max_change_idx is not None and max_change_pct > threshold_pct:
        # Verify the change is sustained: compare the average BEFORE the jump
        # to the average AFTER the jump, and check the jump accounts for most
        # of the total movement.
        pre_avg = sum(daily_values[:max_change_idx]) / max_change_idx
        post_values = daily_values[max_change_idx:]
        post_avg = sum(post_values) / len(post_values)
        total_change = abs(post_avg - pre_avg)
        single_day_change = abs(
            daily_values[max_change_idx] - daily_values[max_change_idx - 1]
        )

        # The single-day jump should account for at least 60% of total shift
        # to qualify as a "step" rather than "gradual drift with one bumpy day"
        if total_change > 0 and (single_day_change / total_change) >= 0.6:
            return {
                "detected": True,
                "change_day_index": max_change_idx,
                "magnitude_pct": round(max_change_pct, 2),
            }

    return {"detected": False, "change_day_index": None, "magnitude_pct": round(max_change_pct, 2)}


# ---------------------------------------------------------------------------
# Function 3: Co-Movement Pattern Matching
# ---------------------------------------------------------------------------

def _direction_matches(observed_value: str, pattern_value: str) -> bool:
    """Check if an observed metric direction matches a pattern's expected direction.

    The co-movement table uses compound directions like "stable_or_up"
    to mean "either stable OR up is acceptable." This function handles
    that flexibility.

    Examples:
        _direction_matches("stable", "stable")       -> True
        _direction_matches("up", "stable_or_up")     -> True
        _direction_matches("stable", "stable_or_up") -> True
        _direction_matches("stable_or_up", "stable_or_up") -> True
        _direction_matches("down", "stable_or_up")   -> False
    """
    # Exact match — most common case
    if observed_value == pattern_value:
        return True

    # If the pattern contains "_or_", it allows multiple directions.
    # Parse the alternatives and check if observed matches any of them.
    if "_or_" in pattern_value:
        allowed = pattern_value.split("_or_")
        # The observed value itself might also be compound (e.g., "stable_or_up")
        # If observed is compound, check if ANY of its components match ANY
        # of the pattern's components.
        if "_or_" in observed_value:
            observed_parts = observed_value.split("_or_")
            return any(op in allowed for op in observed_parts)
        return observed_value in allowed

    # If the observed value is compound but the pattern is simple, no match.
    # e.g., observed="stable_or_up" but pattern="stable" — too loose to claim match.
    if "_or_" in observed_value:
        observed_parts = observed_value.split("_or_")
        return pattern_value in observed_parts

    return False


def match_co_movement_pattern(
    observed: Dict[str, str],
) -> Dict[str, Any]:
    """Match observed metric directions against the co-movement diagnostic table.

    This is the key diagnostic shortcut: instead of decomposing everything,
    first check if the PATTERN of metric movements matches a known failure mode.
    This narrows the hypothesis space before doing expensive decomposition.

    The diagnostic table is loaded from data/knowledge/metric_definitions.yaml.

    Args:
        observed: Dict mapping metric names to directions.
            Keys: dlctr, qsr, sain_trigger, sain_success, zero_result_rate, latency
            Values: "up", "down", "stable", or compound like "stable_or_up"

    Returns:
        {"likely_cause": str, "description": str,
         "priority_hypotheses": list, "is_positive": bool}
    """
    # Load the diagnostic table from YAML
    table = _load_co_movement_table()

    for entry in table:
        pattern = entry["pattern"]

        # Check if every field in the pattern matches the observed directions.
        # All fields must match for the pattern to be considered a match.
        all_match = True
        for metric_key, expected_direction in pattern.items():
            observed_direction = observed.get(metric_key)
            if observed_direction is None:
                # Missing observed metric = can't confirm this pattern
                all_match = False
                break
            if not _direction_matches(observed_direction, expected_direction):
                all_match = False
                break

        if all_match:
            return {
                "likely_cause": entry["likely_cause"],
                "description": entry.get("description", ""),
                "priority_hypotheses": entry.get("priority_hypotheses", []),
                "is_positive": entry.get("is_positive", False),
            }

    # No pattern matched — this is a novel or ambiguous situation.
    # The diagnostic workflow should fall back to full decomposition.
    return {
        "likely_cause": "unknown_pattern",
        "description": "Observed metric directions do not match any known co-movement pattern.",
        "priority_hypotheses": [],
        "is_positive": False,
    }


# ---------------------------------------------------------------------------
# Function 4: Baseline Comparison (Z-Score)
# ---------------------------------------------------------------------------

def check_against_baseline(
    current_value: float,
    metric_name: str,
    segment: Optional[str],
    baselines: Dict[str, float],
) -> Dict[str, Any]:
    """Compare a current metric value against its expected baseline using z-scores.

    This answers: "Is this value unusual?" A z-score tells you how many
    standard deviations away from the mean the current value is.

    Rule of thumb:
    - |z| < 2.0 -> normal weekly variation (happens ~5% of the time)
    - |z| >= 2.0 -> anomalous, worth investigating

    Args:
        current_value: The metric's current observed value.
        metric_name:   Name of the metric (e.g., "dlctr") for labeling.
        segment:       Optional segment name (e.g., "ai_on") for context.
        baselines:     Dict with "mean" and "weekly_std" keys representing
                       the expected baseline distribution.

    Returns:
        {"status": "normal"|"anomalous", "z_score": float, "metric_name": str,
         "segment": str|None, "current_value": float, "baseline_mean": float,
         "baseline_std": float}
    """
    mean = baselines["mean"]
    std = baselines["weekly_std"]

    # Guard against zero std (would cause division by zero).
    # A zero std means the metric never varies, so ANY deviation is anomalous.
    if std < 1e-12:
        z_score = 0.0 if abs(current_value - mean) < 1e-12 else float("inf")
    else:
        z_score = (current_value - mean) / std

    # Classify: is this value within normal variation or not?
    status = "anomalous" if abs(z_score) >= ZSCORE_ANOMALY_THRESHOLD else "normal"

    return {
        "status": status,
        "z_score": round(z_score, 4),
        "metric_name": metric_name,
        "segment": segment,
        "current_value": current_value,
        "baseline_mean": mean,
        "baseline_std": std,
    }


# ---------------------------------------------------------------------------
# CLI Interface — called by Claude Code as a shell command
# ---------------------------------------------------------------------------

def _load_csv_rows(path: str) -> List[Dict[str, str]]:
    """Load a CSV file into a list of dicts (all values as strings)."""
    with open(path, "r") as f:
        return list(csv.DictReader(f))


def _parse_float(value: str) -> float:
    """Safely parse a string to float, returning 0.0 on failure."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def main() -> None:
    """CLI entrypoint: run anomaly detection on a CSV file.

    Example:
        python tools/anomaly.py --input data.csv --metric dlctr_value
        python tools/anomaly.py --input data.csv --check data_quality
        python tools/anomaly.py --input data.csv --check co_movement \
            --directions '{"dlctr":"down","qsr":"down",...}'
    """
    parser = argparse.ArgumentParser(
        description="Anomaly detection for Enterprise Search metrics"
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to CSV file with metric data"
    )
    parser.add_argument(
        "--metric", default="dlctr_value",
        help="Column name of the metric to analyze (default: dlctr_value)"
    )
    parser.add_argument(
        "--check", default="all",
        choices=["all", "data_quality", "step_change", "co_movement", "baseline"],
        help="Which check to run (default: all)"
    )
    parser.add_argument(
        "--directions", default=None,
        help="JSON string of observed metric directions for co-movement check"
    )
    parser.add_argument(
        "--baseline-mean", type=float, default=None,
        help="Expected baseline mean for the metric"
    )
    parser.add_argument(
        "--baseline-std", type=float, default=None,
        help="Expected baseline weekly standard deviation"
    )
    parser.add_argument(
        "--threshold-pct", type=float, default=2.0,
        help="Step-change threshold in percent (default: 2.0)"
    )

    args = parser.parse_args()

    # Load the CSV data
    rows = _load_csv_rows(args.input)

    results: Dict[str, Any] = {}

    # --- Data Quality Check ---
    if args.check in ("all", "data_quality"):
        # Convert string values to float for quality check
        quality_rows = [
            {
                "data_completeness": _parse_float(r.get("data_completeness", "0")),
                "data_freshness_min": _parse_float(r.get("data_freshness_min", "0")),
            }
            for r in rows
        ]
        results["data_quality"] = check_data_quality(quality_rows)

    # --- Step-Change Detection ---
    if args.check in ("all", "step_change"):
        # Group by date and compute daily averages for the target metric
        daily_buckets: Dict[str, List[float]] = {}
        for r in rows:
            # Try to extract date from common timestamp columns
            ts = r.get("metric_ts", r.get("date", r.get("event_ts", "")))
            date_str = ts[:10] if ts else "unknown"
            val = _parse_float(r.get(args.metric, "0"))
            daily_buckets.setdefault(date_str, []).append(val)

        # Compute daily averages, sorted by date
        sorted_dates = sorted(daily_buckets.keys())
        daily_avgs = [
            sum(daily_buckets[d]) / len(daily_buckets[d])
            for d in sorted_dates
        ]

        results["step_change"] = detect_step_change(
            daily_avgs, threshold_pct=args.threshold_pct
        )

    # --- Co-Movement Pattern Matching ---
    if args.check in ("all", "co_movement"):
        if args.directions:
            observed = json.loads(args.directions)
            results["co_movement"] = match_co_movement_pattern(observed)
        else:
            results["co_movement"] = {
                "error": "Provide --directions JSON for co-movement check"
            }

    # --- Baseline Comparison ---
    if args.check in ("all", "baseline"):
        if args.baseline_mean is not None and args.baseline_std is not None:
            # Compute current average of the target metric
            values = [_parse_float(r.get(args.metric, "0")) for r in rows]
            current_avg = sum(values) / len(values) if values else 0.0

            results["baseline"] = check_against_baseline(
                current_value=current_avg,
                metric_name=args.metric,
                segment=None,
                baselines={
                    "mean": args.baseline_mean,
                    "weekly_std": args.baseline_std,
                },
            )
        else:
            results["baseline"] = {
                "error": "Provide --baseline-mean and --baseline-std"
            }

    # Output JSON to stdout for Claude Code to parse
    json.dump(results, sys.stdout, indent=2)
    print()  # trailing newline for clean output


if __name__ == "__main__":
    main()
