#!/usr/bin/env python3
"""Diagnosis tool: validation checks and confidence scoring for metric movements.

This tool consumes output from decompose.py (dimensional decomposition) and
anomaly.py (step-change detection) to validate a diagnosis and assign a
confidence level.

WHY THIS MATTERS:
Raw decomposition tells you WHERE a metric moved (e.g., "standard tier dropped").
But that's not enough -- you need to validate the diagnosis:
- Is it a real behavioral change or a logging artifact? (Check #1)
- Do the segments fully explain the movement? (Check #2)
- Did the cause actually precede the effect? (Check #3)
- Is the movement driven by traffic mix changes? (Check #4)

Only after passing these checks can we confidently assign a root cause.

Usage (CLI):
    python tools/diagnose.py --input decomposition.json

Usage (from Python):
    from tools.diagnose import run_diagnosis
    result = run_diagnosis(decomposition=decomp_output)

Output: JSON to stdout (Claude Code reads this).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────
# Thresholds — from the diagnostic workflow design doc
# ──────────────────────────────────────────────────

# Decomposition completeness: how much of the total drop must segments explain
COMPLETENESS_PASS_THRESHOLD = 90.0    # >=90% explained = segments tell the full story
COMPLETENESS_WARN_THRESHOLD = 70.0    # 70-90% = some unexplained residual
# Below 70% = too much unexplained, can't trust the decomposition

# Mix-shift threshold: when composition change is a significant factor
MIX_SHIFT_INVESTIGATE_THRESHOLD = 30.0  # >=30% mix-shift contribution = investigate

# Confidence scoring thresholds
HIGH_CONFIDENCE_EXPLAINED_PCT = 90.0   # Need >=90% explained for High confidence
HIGH_CONFIDENCE_EVIDENCE_LINES = 3     # Need >=3 supporting evidence lines
MEDIUM_CONFIDENCE_EXPLAINED_PCT = 80.0  # Need >=80% explained for Medium confidence
MEDIUM_CONFIDENCE_EVIDENCE_LINES = 2    # Need >=2 evidence lines


# ──────────────────────────────────────────────────
# Validation Check #1: Logging Artifact Detection
# ──────────────────────────────────────────────────

def check_logging_artifact(step_change_result: Dict[str, Any]) -> Dict[str, Any]:
    """Check if the metric movement is a logging artifact (overnight step-change).

    This is the FIRST check in the validation pipeline because logging artifacts
    are the most common false alarm in Enterprise Search metrics. If a metric
    drops overnight with a clean step-change pattern, it's likely a deploy,
    config change, or instrumentation issue -- not a quality regression.

    WHY CHECK THIS FIRST:
    Chasing a "quality regression" that's actually a logging bug wastes
    days of engineering time. This check prevents that.

    Args:
        step_change_result: Output from anomaly.detect_step_change().
            Expected keys: "detected" (bool), "change_day_index" (int|None),
            "magnitude_pct" (float).

    Returns:
        Dict with:
            - check: "logging_artifact" (always, for identification)
            - status: "HALT" if step-change detected (stop, verify logging),
                      "PASS" if no step-change (safe to proceed)
            - detail: Human-readable explanation of the finding
    """
    if step_change_result.get("detected", False):
        # Step-change found -- this could be a deploy, config change, or logging bug.
        # HALT means: don't proceed with root cause analysis until you verify
        # that the data is trustworthy.
        day_idx = step_change_result.get("change_day_index", "unknown")
        magnitude = step_change_result.get("magnitude_pct", 0.0)
        return {
            "check": "logging_artifact",
            "status": "HALT",
            "detail": (
                f"Overnight step-change detected at day index {day_idx} "
                f"with {magnitude}% magnitude. Verify logging/instrumentation "
                f"before proceeding with diagnosis."
            ),
        }

    # No step-change -- the metric movement looks organic (gradual or spread out).
    # Safe to proceed with decomposition-based diagnosis.
    return {
        "check": "logging_artifact",
        "status": "PASS",
        "detail": "No overnight step-change detected. Movement appears organic.",
    }


# ──────────────────────────────────────────────────
# Validation Check #2: Decomposition Completeness
# ──────────────────────────────────────────────────

def check_decomposition_completeness(explained_pct: float) -> Dict[str, Any]:
    """Check if the dimensional decomposition explains enough of the total drop.

    When we decompose a metric movement by dimensions (e.g., tenant_tier),
    the sum of segment contributions should ideally be ~100%. If a large
    chunk is unexplained, our decomposition is missing a key dimension
    and the diagnosis is unreliable.

    Think of it like a funnel analysis: if you can only account for 70%
    of drop-off, there's a hidden leak somewhere you haven't found.

    Thresholds:
        >=90%: PASS -- segments tell the full story
        70-90%: WARN -- some residual, but diagnosis is still directionally useful
        <70%: HALT -- too much unexplained, add more dimensions before diagnosing

    Args:
        explained_pct: Percentage of total drop explained by identified segments.
            Comes from the dominant segment's contribution_pct in decomposition output.

    Returns:
        Dict with check name, status (PASS/WARN/HALT), and detail string.
    """
    if explained_pct >= COMPLETENESS_PASS_THRESHOLD:
        return {
            "check": "decomposition_completeness",
            "status": "PASS",
            "detail": (
                f"Segments explain {explained_pct:.1f}% of the total movement. "
                f"Decomposition is complete."
            ),
        }

    if explained_pct >= COMPLETENESS_WARN_THRESHOLD:
        # Between 70% and 90% -- usable but imperfect.
        # The analyst should be aware that ~10-30% is unexplained.
        return {
            "check": "decomposition_completeness",
            "status": "WARN",
            "detail": (
                f"Segments explain only {explained_pct:.1f}% of the total movement. "
                f"Consider adding more dimensions to improve coverage."
            ),
        }

    # Below 70% -- the decomposition is too incomplete to trust.
    # There's a major factor we're not capturing.
    return {
        "check": "decomposition_completeness",
        "status": "HALT",
        "detail": (
            f"Segments explain only {explained_pct:.1f}% of the total movement. "
            f"Decomposition is incomplete -- add more dimensions or check data quality."
        ),
    }


# ──────────────────────────────────────────────────
# Validation Check #3: Temporal Consistency
# ──────────────────────────────────────────────────

def check_temporal_consistency(
    cause_date_index: int,
    metric_change_date_index: int,
) -> Dict[str, Any]:
    """Check that the proposed cause precedes (or coincides with) the metric change.

    This is a basic causal reasoning check: if we hypothesize that a code deploy
    caused a DLCTR drop, the deploy must have happened BEFORE or ON the same day
    as the drop. If the metric changed BEFORE the proposed cause, our hypothesis
    is wrong.

    This catches a common diagnostic error: "We deployed feature X on Tuesday,
    and DLCTR dropped on Monday" -- clearly X didn't cause the drop.

    Args:
        cause_date_index: Day index when the proposed cause occurred.
        metric_change_date_index: Day index when the metric actually changed.

    Returns:
        Dict with check name, status (PASS/HALT), and detail string.
    """
    if cause_date_index <= metric_change_date_index:
        # Cause precedes or coincides with effect -- temporally consistent
        gap = metric_change_date_index - cause_date_index
        return {
            "check": "temporal_consistency",
            "status": "PASS",
            "detail": (
                f"Cause (day {cause_date_index}) precedes metric change "
                f"(day {metric_change_date_index}) by {gap} day(s). "
                f"Temporal ordering is consistent."
            ),
        }

    # Metric changed BEFORE the proposed cause -- this breaks causality.
    # The hypothesis needs to be revised.
    gap = cause_date_index - metric_change_date_index
    return {
        "check": "temporal_consistency",
        "status": "HALT",
        "detail": (
            f"Metric changed (day {metric_change_date_index}) BEFORE proposed "
            f"cause (day {cause_date_index}) by {gap} day(s). "
            f"Temporal ordering is inconsistent -- revise hypothesis."
        ),
    }


# ──────────────────────────────────────────────────
# Validation Check #4: Mix-Shift Threshold
# ──────────────────────────────────────────────────

def check_mix_shift_threshold(mix_shift_pct: float) -> Dict[str, Any]:
    """Check if traffic composition change (mix-shift) is a significant factor.

    Mix-shift means the aggregate metric moved because the MIX of traffic
    changed (e.g., more standard-tier tenants), not because behavior changed
    within any segment. When mix-shift is >=30%, the analyst should investigate
    whether the movement is compositional rather than behavioral.

    WHY 30%?
    Below 30%, behavioral change dominates and the diagnosis can focus on
    segment-level quality changes. Above 30%, the composition effect is
    large enough to be the primary driver or a confounding factor.

    Args:
        mix_shift_pct: Percentage of total movement attributed to composition change.
            Comes from decompose.compute_mix_shift().

    Returns:
        Dict with check name, status (INVESTIGATE/PASS), and detail string.
    """
    if mix_shift_pct >= MIX_SHIFT_INVESTIGATE_THRESHOLD:
        # Mix-shift is a significant factor -- the aggregate movement may be
        # driven by traffic composition change, not quality regression.
        return {
            "check": "mix_shift",
            "status": "INVESTIGATE",
            "detail": (
                f"Mix-shift accounts for {mix_shift_pct:.1f}% of the movement "
                f"(threshold: {MIX_SHIFT_INVESTIGATE_THRESHOLD}%). "
                f"Investigate whether this is compositional, not behavioral."
            ),
        }

    # Mix-shift is small -- the movement is primarily behavioral.
    return {
        "check": "mix_shift",
        "status": "PASS",
        "detail": (
            f"Mix-shift accounts for only {mix_shift_pct:.1f}% of the movement. "
            f"Behavioral change dominates."
        ),
    }


# ──────────────────────────────────────────────────
# Confidence Scoring
# ──────────────────────────────────────────────────

def compute_confidence(
    checks: List[Dict[str, Any]],
    explained_pct: float,
    evidence_lines: int,
    has_historical_precedent: bool,
) -> Dict[str, Any]:
    """Assign a confidence level to the diagnosis based on validation results.

    Confidence is a summary judgment: how much should we trust this diagnosis?
    It combines multiple signals:
    - Did all validation checks pass?
    - How much of the movement is explained?
    - How many independent evidence lines support the conclusion?
    - Have we seen this pattern before (historical precedent)?

    Levels:
        High:   All checks PASS + >=90% explained + >=3 evidence lines + precedent
        Medium: >=80% explained + >=2 evidence lines, OR one non-PASS check
        Low:    Single evidence line, OR <80% explained, OR multiple non-PASS checks

    Also includes actionable upgrade/downgrade conditions:
    - would_upgrade_if: What would move confidence UP one level
    - would_downgrade_if: What would move confidence DOWN one level

    Args:
        checks: List of validation check results (each has "status" key).
        explained_pct: Percentage of movement explained by decomposition.
        evidence_lines: Number of independent supporting evidence lines.
        has_historical_precedent: Whether this pattern has been seen before.

    Returns:
        Dict with level, reasoning, would_upgrade_if, would_downgrade_if.
    """
    # Count how many checks are not PASS (HALT, WARN, INVESTIGATE all count)
    non_pass_checks = [c for c in checks if c.get("status") != "PASS"]
    non_pass_count = len(non_pass_checks)

    # Determine any HALT checks (most severe -- blocks diagnosis)
    halt_checks = [c for c in checks if c.get("status") == "HALT"]

    # ── High Confidence ──
    # All conditions must be met simultaneously:
    # 1. All checks PASS (no warnings, no halts, no investigate flags)
    # 2. Segments explain >=90% of the movement
    # 3. At least 3 independent evidence lines
    # 4. Historical precedent exists (we've seen this pattern before)
    all_checks_pass = non_pass_count == 0
    high_explained = explained_pct >= HIGH_CONFIDENCE_EXPLAINED_PCT
    high_evidence = evidence_lines >= HIGH_CONFIDENCE_EVIDENCE_LINES
    high_precedent = has_historical_precedent

    if all_checks_pass and high_explained and high_evidence and high_precedent:
        # Build the downgrade condition: what would make us less confident?
        downgrade_reasons = []
        if explained_pct < 95:
            downgrade_reasons.append("explained_pct drops below 90%")
        if evidence_lines == HIGH_CONFIDENCE_EVIDENCE_LINES:
            downgrade_reasons.append("losing one evidence line")
        downgrade_str = "; ".join(downgrade_reasons) if downgrade_reasons else None

        return {
            "level": "High",
            "reasoning": (
                f"All {len(checks)} validation checks passed. "
                f"{explained_pct:.1f}% of movement explained. "
                f"{evidence_lines} evidence lines with historical precedent."
            ),
            "would_upgrade_if": None,  # Already at highest level
            "would_downgrade_if": downgrade_str,
        }

    # ── Low Confidence ──
    # Any of these conditions triggers Low:
    # 1. Only a single evidence line (too little corroboration)
    # 2. Less than 80% of movement explained (decomposition incomplete)
    # 3. Multiple non-PASS checks (compound problems)
    low_evidence = evidence_lines < MEDIUM_CONFIDENCE_EVIDENCE_LINES
    low_explained = explained_pct < MEDIUM_CONFIDENCE_EXPLAINED_PCT
    multiple_non_pass = non_pass_count >= 2

    if low_evidence or low_explained or multiple_non_pass:
        # Build upgrade conditions: what would move us to Medium?
        upgrade_reasons = []
        if low_evidence:
            upgrade_reasons.append(
                f"increase evidence lines from {evidence_lines} to "
                f">={MEDIUM_CONFIDENCE_EVIDENCE_LINES}"
            )
        if low_explained:
            upgrade_reasons.append(
                f"increase explained_pct from {explained_pct:.1f}% to "
                f">={MEDIUM_CONFIDENCE_EXPLAINED_PCT}%"
            )
        if multiple_non_pass:
            upgrade_reasons.append(
                f"resolve {non_pass_count - 1} of {non_pass_count} failing checks"
            )
        upgrade_str = "; ".join(upgrade_reasons) if upgrade_reasons else None

        return {
            "level": "Low",
            "reasoning": (
                f"Low confidence due to: "
                + (f"only {evidence_lines} evidence line(s). " if low_evidence else "")
                + (f"{explained_pct:.1f}% explained (need >={MEDIUM_CONFIDENCE_EXPLAINED_PCT}%). " if low_explained else "")
                + (f"{non_pass_count} non-PASS checks. " if multiple_non_pass else "")
            ).rstrip(),
            "would_upgrade_if": upgrade_str,
            "would_downgrade_if": None,  # Already at lowest level
        }

    # ── Medium Confidence ──
    # Not High (missing at least one High condition) and not Low (no Low triggers).
    # This is the "good enough to act on, but verify" zone.
    # Typical cases: >=80% explained + >=2 evidence, or one non-PASS check.

    # Build upgrade conditions: what would make this High?
    upgrade_reasons = []
    if not high_explained:
        upgrade_reasons.append(
            f"increase explained_pct from {explained_pct:.1f}% to "
            f">={HIGH_CONFIDENCE_EXPLAINED_PCT}%"
        )
    if not high_evidence:
        upgrade_reasons.append(
            f"add {HIGH_CONFIDENCE_EVIDENCE_LINES - evidence_lines} more evidence line(s)"
        )
    if not high_precedent:
        upgrade_reasons.append("find historical precedent for this pattern")
    if not all_checks_pass:
        non_pass_names = [
            c.get("check", "unknown") for c in non_pass_checks
        ]
        upgrade_reasons.append(
            f"resolve non-PASS check(s): {', '.join(non_pass_names)}"
        )
    upgrade_str = "; ".join(upgrade_reasons) if upgrade_reasons else None

    # Build downgrade conditions
    downgrade_reasons = []
    if evidence_lines == MEDIUM_CONFIDENCE_EVIDENCE_LINES:
        downgrade_reasons.append("losing one evidence line")
    if explained_pct < 85:
        downgrade_reasons.append(f"explained_pct drops below {MEDIUM_CONFIDENCE_EXPLAINED_PCT}%")
    downgrade_str = "; ".join(downgrade_reasons) if downgrade_reasons else None

    return {
        "level": "Medium",
        "reasoning": (
            f"Medium confidence: {explained_pct:.1f}% explained, "
            f"{evidence_lines} evidence line(s), "
            f"{non_pass_count} non-PASS check(s), "
            f"historical precedent: {has_historical_precedent}."
        ),
        "would_upgrade_if": upgrade_str,
        "would_downgrade_if": downgrade_str,
    }


# ──────────────────────────────────────────────────
# Full Diagnosis Pipeline
# ──────────────────────────────────────────────────

def _extract_explained_pct(decomposition: Dict[str, Any]) -> float:
    """Extract the explained percentage from decomposition output.

    The "explained percentage" is the dominant segment's contribution_pct
    from the first dimension in the dimensional breakdown. This tells us
    how much of the total movement the top contributor accounts for.

    If there are multiple dimensions, we take the one with the highest
    dominant contribution, since that's the most explanatory dimension.

    Args:
        decomposition: Output from decompose.run_decomposition()

    Returns:
        Float percentage (0-100). Returns 0.0 if no dimensional data.
    """
    dimensional = decomposition.get("dimensional_breakdown", {})
    if not dimensional:
        return 0.0

    # Find the dimension with the highest total explained percentage.
    # Sum up all segment contributions for each dimension to get total explained.
    max_explained = 0.0
    for dim_name, dim_result in dimensional.items():
        segments = dim_result.get("segments", [])
        if segments:
            # Sum absolute contributions of all segments in this dimension.
            # This represents how much of the movement this dimension explains.
            total_contribution = sum(
                abs(s.get("contribution_pct", 0)) for s in segments
            )
            if total_contribution > max_explained:
                max_explained = total_contribution

    return max_explained


def _extract_mix_shift_pct(decomposition: Dict[str, Any]) -> float:
    """Extract the mix-shift percentage from decomposition output.

    Args:
        decomposition: Output from decompose.run_decomposition()

    Returns:
        Float percentage (0-100). Returns 0.0 if no mix-shift data.
    """
    mix_shift = decomposition.get("mix_shift", {})
    return mix_shift.get("mix_shift_contribution_pct", 0.0)


def _build_primary_hypothesis(decomposition: Dict[str, Any]) -> Dict[str, Any]:
    """Build a primary hypothesis from the decomposition results.

    The hypothesis identifies the most likely root cause dimension and segment.
    For example: "The DLCTR drop is concentrated in the standard tenant tier."

    Args:
        decomposition: Output from decompose.run_decomposition()

    Returns:
        Dict with dimension, segment, contribution_pct, and description.
    """
    dominant_dim = decomposition.get("dominant_dimension")
    dimensional = decomposition.get("dimensional_breakdown", {})
    aggregate = decomposition.get("aggregate", {})

    if not dominant_dim or dominant_dim not in dimensional:
        return {
            "dimension": None,
            "segment": None,
            "contribution_pct": 0.0,
            "description": "No dominant dimension identified from decomposition.",
        }

    dim_result = dimensional[dominant_dim]
    segments = dim_result.get("segments", [])
    if not segments:
        return {
            "dimension": dominant_dim,
            "segment": None,
            "contribution_pct": 0.0,
            "description": f"Dimension '{dominant_dim}' has no segments.",
        }

    # Top segment is already sorted by absolute contribution
    top_segment = segments[0]
    metric_name = aggregate.get("metric", "metric")
    direction = aggregate.get("direction", "changed")

    return {
        "dimension": dominant_dim,
        "segment": top_segment["segment_value"],
        "contribution_pct": top_segment["contribution_pct"],
        "description": (
            f"The {metric_name} movement is concentrated in "
            f"{dominant_dim}='{top_segment['segment_value']}' "
            f"(contributing {top_segment['contribution_pct']:.1f}% of total change). "
            f"Segment {direction} from {top_segment['baseline_mean']:.4f} "
            f"to {top_segment['current_mean']:.4f}."
        ),
    }


def _build_action_items(
    checks: List[Dict[str, Any]],
    confidence_level: str,
    decomposition: Dict[str, Any],
) -> List[str]:
    """Generate actionable next steps based on validation results.

    Each non-PASS check generates a specific action item. The confidence
    level and decomposition results inform additional recommendations.

    Args:
        checks: List of validation check results.
        confidence_level: "High", "Medium", or "Low".
        decomposition: Original decomposition output.

    Returns:
        List of action item strings.
    """
    actions = []

    # Generate actions from non-PASS checks
    for check in checks:
        status = check.get("status", "PASS")
        check_name = check.get("check", "unknown")

        if status == "HALT":
            if check_name == "logging_artifact":
                actions.append(
                    "PRIORITY: Verify logging and instrumentation pipeline "
                    "before proceeding. Check recent deploys and config changes."
                )
            elif check_name == "decomposition_completeness":
                actions.append(
                    "Add more decomposition dimensions (e.g., connector_type, "
                    "query_type) to improve coverage of the unexplained residual."
                )
            elif check_name == "temporal_consistency":
                actions.append(
                    "Revise the causal hypothesis -- the proposed cause does not "
                    "precede the metric change. Look for earlier events."
                )
        elif status == "WARN":
            actions.append(
                f"Check '{check_name}' is in WARN state: {check.get('detail', '')}. "
                f"Consider investigating further."
            )
        elif status == "INVESTIGATE":
            if check_name == "mix_shift":
                actions.append(
                    "Investigate mix-shift: the movement may be driven by traffic "
                    "composition change rather than quality regression. "
                    "Compare per-segment metrics to confirm."
                )

    # Confidence-based recommendations
    if confidence_level == "Low":
        actions.append(
            "Low confidence diagnosis -- gather more evidence before acting. "
            "Consider running additional decomposition dimensions."
        )
    elif confidence_level == "Medium":
        actions.append(
            "Medium confidence -- directionally useful but verify with "
            "additional data before escalating."
        )

    # Drill-down recommendation from decomposition
    if decomposition.get("drill_down_recommended", False):
        dominant_dim = decomposition.get("dominant_dimension")
        if dominant_dim:
            actions.append(
                f"Drill down into '{dominant_dim}' dimension for segment-level "
                f"root cause analysis."
            )

    return actions


def run_diagnosis(
    decomposition: Dict[str, Any],
    step_change_result: Optional[Dict[str, Any]] = None,
    cause_date_index: Optional[int] = None,
    metric_change_date_index: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the full diagnosis pipeline on decomposition output.

    This is the main entry point for the diagnosis tool. It orchestrates
    all 4 validation checks, computes confidence, and generates a complete
    diagnosis report.

    The pipeline:
    1. Check for logging artifacts (step-change detection)
    2. Check decomposition completeness (segment coverage)
    3. Check temporal consistency (cause precedes effect)
    4. Check mix-shift threshold (compositional vs behavioral)
    5. Compute confidence level from all checks + evidence
    6. Build primary hypothesis and action items

    Args:
        decomposition: Output from decompose.run_decomposition().
            Must contain: aggregate, dimensional_breakdown, mix_shift.
        step_change_result: Output from anomaly.detect_step_change().
            If None, defaults to no step-change detected.
        cause_date_index: Day index of the proposed cause event.
            If None, defaults to 0 (assumes cause is at the start).
        metric_change_date_index: Day index when the metric changed.
            If None, defaults to 0 (no temporal check possible).

    Returns:
        Dict with: aggregate, primary_hypothesis, confidence,
        validation_checks, dimensional_breakdown, mix_shift, action_items.
    """
    # ── Defaults for optional parameters ──
    # If no step-change result provided, assume no step-change detected.
    # This is safe: we're just saying "we haven't checked for step changes."
    if step_change_result is None:
        step_change_result = {"detected": False, "change_day_index": None, "magnitude_pct": 0.0}

    # If no temporal indices provided, default to 0 (cause == metric change).
    # This means the temporal check will PASS by default, which is the safe
    # assumption when we don't have timing information.
    if cause_date_index is None:
        cause_date_index = 0
    if metric_change_date_index is None:
        metric_change_date_index = 0

    # ── Extract key metrics from decomposition ──
    explained_pct = _extract_explained_pct(decomposition)
    mix_shift_pct = _extract_mix_shift_pct(decomposition)

    # ── Run all 4 validation checks ──
    check_1 = check_logging_artifact(step_change_result)
    check_2 = check_decomposition_completeness(explained_pct)
    check_3 = check_temporal_consistency(cause_date_index, metric_change_date_index)
    check_4 = check_mix_shift_threshold(mix_shift_pct)

    all_checks = [check_1, check_2, check_3, check_4]

    # ── Count evidence lines ──
    # Evidence lines are independent signals supporting the diagnosis:
    # 1. Dimensional decomposition identified a dominant segment
    # 2. Mix-shift analysis confirms behavioral (not compositional) change
    # 3. Aggregate severity classification is meaningful (not "normal")
    evidence_lines = 0

    # Evidence: decomposition found a dominant segment
    if decomposition.get("drill_down_recommended", False):
        evidence_lines += 1

    # Evidence: mix-shift is small (movement is behavioral)
    if mix_shift_pct < MIX_SHIFT_INVESTIGATE_THRESHOLD:
        evidence_lines += 1

    # Evidence: aggregate severity is meaningful (P0, P1, or P2)
    aggregate = decomposition.get("aggregate", {})
    if aggregate.get("severity") in ("P0", "P1", "P2"):
        evidence_lines += 1

    # Historical precedent: currently not tracked in decomposition output.
    # Default to False. Future enhancement: check against past diagnoses.
    has_historical_precedent = False

    # ── Compute confidence ──
    confidence = compute_confidence(
        checks=all_checks,
        explained_pct=explained_pct,
        evidence_lines=evidence_lines,
        has_historical_precedent=has_historical_precedent,
    )

    # ── Build hypothesis and action items ──
    primary_hypothesis = _build_primary_hypothesis(decomposition)
    action_items = _build_action_items(all_checks, confidence["level"], decomposition)

    # ── Assemble the full diagnosis report ──
    return {
        "aggregate": aggregate,
        "primary_hypothesis": primary_hypothesis,
        "confidence": confidence,
        "validation_checks": all_checks,
        "dimensional_breakdown": decomposition.get("dimensional_breakdown", {}),
        "mix_shift": decomposition.get("mix_shift", {}),
        "action_items": action_items,
    }


# ──────────────────────────────────────────────────
# CLI interface -- for Claude Code to call via Bash tool
# ──────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Run validation checks and confidence scoring on decomposition output"
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to JSON file with decomposition output (from decompose.py)"
    )
    parser.add_argument(
        "--step-change-json", default=None,
        help="Path to JSON file with step-change result (from anomaly.py)"
    )
    parser.add_argument(
        "--cause-day", type=int, default=None,
        help="Day index of the proposed cause event"
    )
    parser.add_argument(
        "--metric-change-day", type=int, default=None,
        help="Day index when the metric changed"
    )
    return parser.parse_args()


def main():
    """CLI entry point: load decomposition JSON, run diagnosis, print JSON to stdout."""
    args = parse_args()

    # Load the decomposition output JSON
    input_path = Path(args.input)
    if not input_path.exists():
        print(json.dumps({"error": f"File not found: {args.input}"}))
        sys.exit(1)

    with open(input_path) as f:
        decomposition = json.load(f)

    # Optionally load step-change result
    step_change_result = None
    if args.step_change_json:
        sc_path = Path(args.step_change_json)
        if sc_path.exists():
            with open(sc_path) as f:
                step_change_result = json.load(f)
        else:
            print(json.dumps({"error": f"Step-change file not found: {args.step_change_json}"}))
            sys.exit(1)

    # Run the full diagnosis
    result = run_diagnosis(
        decomposition=decomposition,
        step_change_result=step_change_result,
        cause_date_index=args.cause_day,
        metric_change_date_index=args.metric_change_day,
    )

    # Output JSON to stdout for Claude Code to read
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
