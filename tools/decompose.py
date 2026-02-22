#!/usr/bin/env python3
"""Dimensional decomposition and mix-shift analysis for Search metrics.

This tool breaks a metric movement into dimensional contributions and
separates behavioral changes (actual quality change) from mix-shift
(population composition change).

WHY THIS MATTERS:
In Enterprise Search, aggregate metric drops often have simple explanations:
- A single tenant tier is degrading (dimensional decomposition finds this)
- The mix of traffic shifted toward lower-performing segments (mix-shift finds this)
Distinguishing these two is critical because they require different responses.

Usage (CLI):
    python tools/decompose.py --input data.csv --metric dlctr_value --dimensions tenant_tier,ai_enablement

Usage (from Python):
    from tools.decompose import run_decomposition
    result = run_decomposition(rows, "dlctr_value", dimensions=["tenant_tier"])

Output: JSON to stdout (Claude Code reads this).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────
# Severity classification thresholds
# Matches design doc Section 5: P0 (>5%), P1 (2-5%), P2 (0.5-2%), normal (<0.5%)
# These map to urgency: P0 = page on-call, P1 = next standup, P2 = monitor
# ──────────────────────────────────────────────────

SEVERITY_THRESHOLDS = {
    "P0": 0.05,   # >5% relative movement
    "P1": 0.02,   # 2-5%
    "P2": 0.005,  # 0.5-2%
}


def _mean(values: List[float]) -> float:
    """Compute arithmetic mean. Returns 0.0 for empty lists.

    Using our own implementation to avoid importing numpy/statistics
    (project constraint: stdlib only).
    """
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_float(value) -> float:
    """Convert a value to float, handling strings and edge cases.

    CSV readers return strings, so we need this conversion.
    Returns 0.0 for anything that can't be parsed (defensive coding).
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _classify_severity(relative_delta_pct: float) -> str:
    """Classify metric movement severity based on magnitude.

    Uses absolute value because both drops AND spikes can be concerning.
    E.g., a +8% DLCTR spike might indicate a tracking bug.
    """
    magnitude = abs(relative_delta_pct) / 100.0  # convert pct to fraction
    if magnitude >= SEVERITY_THRESHOLDS["P0"]:
        return "P0"
    elif magnitude >= SEVERITY_THRESHOLDS["P1"]:
        return "P1"
    elif magnitude >= SEVERITY_THRESHOLDS["P2"]:
        return "P2"
    return "normal"


def _group_by(rows: List[Dict], dim: str) -> Dict[str, List[Dict]]:
    """Group rows by the value of a dimension field.

    This is a common operation: group by tenant_tier, group by ai_enablement, etc.
    Rows missing the dimension get grouped under "unknown".
    """
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        groups[r.get(dim, "unknown")].append(r)
    return groups


# ──────────────────────────────────────────────────
# Core Analysis Functions
# ──────────────────────────────────────────────────


def compute_aggregate_delta(
    baseline_rows: List[Dict],
    current_rows: List[Dict],
    metric_field: str,
) -> Dict[str, Any]:
    """Compute the headline metric movement between two periods.

    This is the first thing we check: "DLCTR dropped X% WoW."
    Think of it like the top-level KPI dashboard: before diving into
    dimensions, you need to know the overall magnitude and direction.

    Args:
        baseline_rows: Rows from the comparison period (e.g., last week)
        current_rows: Rows from the current period
        metric_field: Which field to analyze (e.g., "dlctr_value")

    Returns:
        Dict with baseline_mean, current_mean, absolute_delta,
        relative_delta_pct, severity, direction, error.
    """
    # Guard: we need data in both periods to compute a delta
    if not baseline_rows or not current_rows:
        return {"error": "Empty input: need both baseline and current rows"}

    # Extract metric values, converting to float (CSV data comes as strings)
    baseline_values = [_safe_float(r.get(metric_field, 0)) for r in baseline_rows]
    current_values = [_safe_float(r.get(metric_field, 0)) for r in current_rows]

    baseline_mean = _mean(baseline_values)
    current_mean = _mean(current_values)

    # Can't compute relative delta with zero baseline (division by zero)
    if baseline_mean == 0:
        return {"error": f"Baseline mean is zero for {metric_field}"}

    absolute_delta = current_mean - baseline_mean
    relative_delta_pct = (absolute_delta / baseline_mean) * 100.0

    # Classify the movement for prioritization
    direction = "up" if absolute_delta > 0 else "down" if absolute_delta < 0 else "stable"
    severity = _classify_severity(relative_delta_pct)

    return {
        "metric": metric_field,
        "baseline_mean": round(baseline_mean, 6),
        "current_mean": round(current_mean, 6),
        "absolute_delta": round(absolute_delta, 6),
        "relative_delta_pct": round(relative_delta_pct, 2),
        "direction": direction,
        "severity": severity,
        "baseline_count": len(baseline_values),
        "current_count": len(current_values),
        "error": None,
    }


def decompose_by_dimension(
    baseline_rows: List[Dict],
    current_rows: List[Dict],
    metric_field: str,
    dimension: str,
) -> Dict[str, Any]:
    """Break a metric movement into contributions by a single dimension.

    For each segment value (e.g., tenant_tier="standard"), compute:
    - How much the metric changed in that segment
    - What % of the total change this segment contributed

    This tells you WHERE the drop is concentrated. In Enterprise Search,
    a DLCTR drop concentrated in "standard" tier tenants is very different
    from one spread across all tiers (the former suggests a tier-specific
    issue, the latter a platform-wide regression).

    Contribution formula:
        contribution = (segment_delta * segment_traffic_share) / overall_delta

    Args:
        baseline_rows: Rows from baseline period
        current_rows: Rows from current period
        metric_field: Metric to analyze
        dimension: Which dimension to segment by (e.g., "tenant_tier")

    Returns:
        Dict with segments list, each containing segment_value, baseline_mean,
        current_mean, delta, contribution_pct.
    """
    # Group rows by segment value for both periods
    baseline_groups = _group_by(baseline_rows, dimension)
    current_groups = _group_by(current_rows, dimension)

    # Need the overall delta to compute what % each segment contributes
    overall = compute_aggregate_delta(baseline_rows, current_rows, metric_field)
    overall_delta = overall["absolute_delta"] if overall["error"] is None else 0.0

    # Union of all segment values across both periods
    all_segments = set(list(baseline_groups.keys()) + list(current_groups.keys()))
    segments = []

    for seg_value in sorted(all_segments):
        bl_values = [_safe_float(r.get(metric_field, 0))
                     for r in baseline_groups.get(seg_value, [])]
        cur_values = [_safe_float(r.get(metric_field, 0))
                      for r in current_groups.get(seg_value, [])]

        bl_mean = _mean(bl_values)
        cur_mean = _mean(cur_values)
        delta = cur_mean - bl_mean

        # Weight by segment's share of current traffic
        # WHY current traffic? Because we want to know what's driving
        # the metric NOW, not what drove it in the past
        cur_weight = len(cur_values) / max(len(current_rows), 1)

        # Contribution: how much of the overall delta comes from this segment
        # Weighted delta = segment_delta * segment_traffic_share
        weighted_delta = delta * cur_weight
        contribution_pct = (
            (weighted_delta / overall_delta * 100.0)
            if overall_delta != 0
            else 0.0
        )

        segments.append({
            "segment_value": seg_value,
            "baseline_mean": round(bl_mean, 6),
            "current_mean": round(cur_mean, 6),
            "delta": round(delta, 6),
            "baseline_count": len(bl_values),
            "current_count": len(cur_values),
            "traffic_share_pct": round(cur_weight * 100, 1),
            "contribution_pct": round(contribution_pct, 1),
        })

    # Sort by contribution magnitude (highest contributor first)
    # This puts the "smoking gun" segment at the top
    segments.sort(key=lambda s: abs(s["contribution_pct"]), reverse=True)

    return {
        "dimension": dimension,
        "overall_delta": overall_delta,
        "segments": segments,
        "dominant_segment": segments[0]["segment_value"] if segments else None,
        "dominant_contribution_pct": segments[0]["contribution_pct"] if segments else 0,
    }


def compute_mix_shift(
    baseline_rows: List[Dict],
    current_rows: List[Dict],
    metric_field: str,
    dimension: str,
) -> Dict[str, Any]:
    """Separate mix-shift from behavioral change for a metric movement.

    Mix-shift = the metric moved because the COMPOSITION of traffic changed
    (e.g., more standard-tier tenants), not because behavior changed within
    any segment.

    Uses the Kitagawa-Oaxaca decomposition:
      Total change = Behavioral effect + Composition effect (mix-shift)

    - Behavioral: hold composition constant, measure metric change per segment
    - Composition: hold segment metrics constant, measure traffic share change

    WHY THIS MATTERS for Enterprise Search:
    Tenant portfolio changes constantly (new tenants onboarding, tier migrations,
    seasonal traffic from specific verticals). These composition changes can
    cause aggregate metric movements that look alarming but require NO action --
    each segment is performing normally, just the mix changed.

    Example: If 20% more standard-tier tenants onboard (who naturally have
    lower DLCTR), aggregate DLCTR drops even though no quality regression
    occurred. The mix-shift analysis catches this.

    Flag threshold: 30% or more mix-shift contribution triggers a flag,
    per design doc validation check #4.
    """
    # Group by dimension for both periods
    baseline_groups = _group_by(baseline_rows, dimension)
    current_groups = _group_by(current_rows, dimension)

    all_segments = set(list(baseline_groups.keys()) + list(current_groups.keys()))
    total_baseline = max(len(baseline_rows), 1)
    total_current = max(len(current_rows), 1)

    behavioral_effect = 0.0
    composition_effect = 0.0

    for seg in all_segments:
        bl_values = [_safe_float(r.get(metric_field, 0))
                     for r in baseline_groups.get(seg, [])]
        cur_values = [_safe_float(r.get(metric_field, 0))
                      for r in current_groups.get(seg, [])]

        bl_mean = _mean(bl_values) if bl_values else 0.0
        cur_mean = _mean(cur_values) if cur_values else 0.0

        # Traffic shares: what fraction of total traffic is this segment?
        bl_share = len(bl_values) / total_baseline
        cur_share = len(cur_values) / total_current

        # Kitagawa-Oaxaca decomposition (symmetric version):
        #
        # Behavioral effect: metric changed within this segment
        # Weight by average share so the decomposition is symmetric
        # (doesn't favor either period's composition)
        avg_share = (bl_share + cur_share) / 2
        behavioral_effect += (cur_mean - bl_mean) * avg_share

        # Composition effect: traffic share changed for this segment
        # Weight by average metric so we measure the impact of the
        # share change at the segment's typical performance level
        avg_metric = (bl_mean + cur_mean) / 2
        composition_effect += (cur_share - bl_share) * avg_metric

    total_effect = behavioral_effect + composition_effect

    # Edge case: no change at all
    if abs(total_effect) < 1e-10:
        return {
            "dimension": dimension,
            "mix_shift_contribution_pct": 0.0,
            "behavioral_contribution_pct": 0.0,
            "total_effect": 0.0,
            "behavioral_effect": 0.0,
            "composition_effect": 0.0,
            "flag": None,
        }

    # Compute percentages using absolute values
    # WHY absolute? Because behavioral and composition effects can have
    # opposite signs (e.g., composition pulls metric down while behavior
    # pushes it up). We want to know the MAGNITUDE of each contribution.
    mix_pct = (abs(composition_effect)
               / (abs(behavioral_effect) + abs(composition_effect)) * 100)
    behavioral_pct = 100.0 - mix_pct

    # Flag if mix-shift exceeds 30% threshold (from design doc validation check #4)
    # This tells the analyst: "be careful, a big chunk of this movement is just
    # traffic composition change, not an actual quality regression"
    flag = "mix_shift_dominant" if mix_pct >= 30 else None

    return {
        "dimension": dimension,
        "mix_shift_contribution_pct": round(mix_pct, 1),
        "behavioral_contribution_pct": round(behavioral_pct, 1),
        "total_effect": round(total_effect, 6),
        "behavioral_effect": round(behavioral_effect, 6),
        "composition_effect": round(composition_effect, 6),
        "flag": flag,
    }


def run_decomposition(
    rows: List[Dict],
    metric_field: str,
    dimensions: Optional[List[str]] = None,
    baseline_period: str = "baseline",
    current_period: str = "current",
    period_field: str = "period",
) -> Dict[str, Any]:
    """Run the full decomposition pipeline on a dataset.

    This is the main entry point called by Claude Code. It orchestrates:
    1. Headline delta (how big is the movement?)
    2. Dimensional decomposition (where is it concentrated?)
    3. Mix-shift analysis (is it real or compositional?)

    Think of it like a diagnostic funnel:
    - First you see the overall drop
    - Then you see which segment is driving it
    - Then you check if it's a real behavioral change or just traffic mix

    Args:
        rows: All rows (both periods)
        metric_field: Which metric to analyze
        dimensions: List of dimensions to decompose by (default: all Enterprise dims)
        baseline_period: Value of period_field for baseline rows
        current_period: Value of period_field for current rows
        period_field: Column name containing period labels

    Returns:
        Dict with aggregate, dimensional_breakdown, mix_shift results.
        JSON-serializable for Claude Code to read.
    """
    # Default dimensions cover the key Enterprise Search segmentation axes
    if dimensions is None:
        dimensions = [
            "tenant_tier", "ai_enablement", "industry_vertical",
            "connector_type", "query_type", "position_bucket",
        ]

    # Split into baseline and current periods
    baseline = [r for r in rows if r.get(period_field) == baseline_period]
    current = [r for r in rows if r.get(period_field) == current_period]

    # Step 1: Headline delta -- "DLCTR dropped 6.25% WoW"
    aggregate = compute_aggregate_delta(baseline, current, metric_field)

    # Step 2: Decompose by each dimension -- "The drop is in standard tier"
    dimensional: Dict[str, Any] = {}
    for dim in dimensions:
        # Only decompose if the dimension actually exists in the data
        # (avoids noise from dimensions not present in this dataset)
        if any(dim in r for r in rows):
            dimensional[dim] = decompose_by_dimension(
                baseline, current, metric_field, dim
            )

    # Step 3: Mix-shift analysis for the primary dimension
    # WHY primary dimension only? Because mix-shift is most meaningful
    # for the highest-level segmentation (tenant_tier in Enterprise Search)
    primary_dim = dimensions[0] if dimensions else None
    mix_shift: Dict[str, Any] = {}
    if primary_dim and any(primary_dim in r for r in rows):
        mix_shift = compute_mix_shift(
            baseline, current, metric_field, primary_dim
        )

    # Identify which dimension explains the most movement
    # This tells the analyst where to focus their investigation
    max_contribution = 0.0
    dominant_dimension = None
    for dim_name, dim_result in dimensional.items():
        if dim_result["segments"]:
            top_contribution = abs(dim_result["segments"][0]["contribution_pct"])
            if top_contribution > max_contribution:
                max_contribution = top_contribution
                dominant_dimension = dim_name

    return {
        "aggregate": aggregate,
        "dimensional_breakdown": dimensional,
        "mix_shift": mix_shift,
        "dominant_dimension": dominant_dimension,
        # Recommend drill-down if one segment explains >50% of the movement
        "drill_down_recommended": max_contribution > 50,
    }


# ──────────────────────────────────────────────────
# CLI interface -- for Claude Code to call via Bash tool
# ──────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Decompose a metric movement by dimensions and detect mix-shift"
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to CSV file with metric data"
    )
    parser.add_argument(
        "--metric", required=True,
        help="Metric column to analyze (e.g., dlctr_value)"
    )
    parser.add_argument(
        "--dimensions", default="tenant_tier,ai_enablement,query_type",
        help="Comma-separated dimensions to decompose by"
    )
    parser.add_argument(
        "--baseline-period", default="baseline",
        help="Value of period column for baseline rows"
    )
    parser.add_argument(
        "--current-period", default="current",
        help="Value of period column for current rows"
    )
    parser.add_argument(
        "--period-field", default="period",
        help="Column name containing period labels"
    )
    return parser.parse_args()


def main():
    """CLI entry point: load CSV, run decomposition, print JSON to stdout."""
    args = parse_args()

    # Load CSV input file
    input_path = Path(args.input)
    if not input_path.exists():
        print(json.dumps({"error": f"File not found: {args.input}"}))
        sys.exit(1)

    with open(input_path) as f:
        rows = list(csv.DictReader(f))

    dimensions = [d.strip() for d in args.dimensions.split(",")]

    result = run_decomposition(
        rows=rows,
        metric_field=args.metric,
        dimensions=dimensions,
        baseline_period=args.baseline_period,
        current_period=args.current_period,
        period_field=args.period_field,
    )

    # Output JSON to stdout for Claude Code to read
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
