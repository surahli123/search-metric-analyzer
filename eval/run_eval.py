#!/usr/bin/env python3
"""MVE Eval Runner: loads scoring specs, evaluates diagnosis output, aggregates results.

This is the eval framework for the Search Metric Analyzer. It implements
the LLM-as-judge evaluation pattern from the design doc (Section 11):

1. Load all scoring specs from eval/scoring_specs/*.yaml
2. For each case: run diagnosis 3 times, evaluate with LLM-as-judge
3. Score each run against the rubric (100-point scale)
4. Aggregate 3 runs into GREEN/YELLOW/RED per case
5. Output summary report

WHY THIS DESIGN:
The 3-run majority vote catches flaky outputs. A tool that scores GREEN
on 2/3 runs but RED on 1 might have a nondeterministic path that sometimes
fails — YELLOW flags this for investigation.

The eval runner is a SKELETON — it scores diagnosis output deterministically
using the rubric criteria. The actual LLM-as-judge integration (calling a
separate model) is stubbed out and will be wired up when we have an API key.

Usage (CLI):
    python eval/run_eval.py                     # Run all cases
    python eval/run_eval.py --case S4           # Run single case
    python eval/run_eval.py --diagnosis out.json # Score a specific diagnosis

Usage (from Python):
    from eval.run_eval import load_scoring_specs, score_single_run, aggregate_runs
    specs = load_scoring_specs()
    result = score_single_run(spec, diagnosis_dict, formatted_output)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Paths ──
EVAL_DIR = Path(__file__).resolve().parent
SPECS_DIR = EVAL_DIR / "scoring_specs"


def _term_in_text(term: str, text: str) -> bool:
    """Check if a term appears as a whole word in text (not substring).

    WHY: Substring matching causes false positives. "metric" should not
    match "parametric", and "normal" should not match "abnormal".
    Using word boundaries (\b) prevents these spurious matches.

    Args:
        term: The word to search for.
        text: The text to search in.

    Returns:
        True if the term appears as a whole word in the text.
    """
    return bool(re.search(r'\b' + re.escape(term) + r'\b', text))


# ──────────────────────────────────────────────────
# Scoring Spec Loader
# ──────────────────────────────────────────────────

def load_scoring_specs(specs_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load all scoring spec YAML files from the scoring_specs/ directory.

    Each spec defines what a correct diagnosis looks like for one eval case:
    rubric criteria, must_find root cause, must_not_do anti-patterns, etc.

    Args:
        specs_dir: Path to scoring_specs directory. Defaults to eval/scoring_specs/.

    Returns:
        List of parsed spec dicts, sorted by filename for deterministic ordering.
    """
    if specs_dir is None:
        specs_dir = SPECS_DIR

    specs = []
    # Sort by filename for consistent ordering across runs
    for yaml_path in sorted(specs_dir.glob("*.yaml")):
        with open(yaml_path) as f:
            spec = yaml.safe_load(f)
        # Attach the filename for reference in reports
        spec["_source_file"] = yaml_path.name
        specs.append(spec)

    return specs


# ──────────────────────────────────────────────────
# Deterministic Rubric Scorer
# ──────────────────────────────────────────────────

def _score_root_cause_accuracy(
    spec: Dict[str, Any],
    diagnosis: Dict[str, Any],
    formatted: Dict[str, str],
) -> Dict[str, Any]:
    """Score the root_cause_accuracy dimension (40 points max).

    Checks whether the diagnosis correctly identifies the root cause
    described in must_find, and doesn't violate any must_not_do rules.

    This is deterministic scoring using keyword/semantic matching —
    the LLM-as-judge version would use a separate model for evaluation.

    Args:
        spec: Scoring spec dict with must_find and rubric.
        diagnosis: Raw diagnosis output dict.
        formatted: Formatted output dict with slack_message and short_report.

    Returns:
        Dict with dimension name, points earned, max points, and details.
    """
    rubric = spec["rubric"]["root_cause_accuracy"]
    max_points = rubric["weight"]
    earned = 0
    details = []

    # Get the hypothesis description from the diagnosis
    hypothesis = diagnosis.get("primary_hypothesis", {})
    hypothesis_desc = hypothesis.get("description", "").lower()
    report_text = formatted.get("short_report", "").lower()
    slack_text = formatted.get("slack_message", "").lower()
    combined_text = f"{hypothesis_desc} {report_text} {slack_text}"

    # Check must_find: does the output mention the expected root cause?
    must_find = spec["must_find"]
    expected_root = must_find["root_cause"].lower()

    # Semantic matching: check if key terms from expected root cause appear.
    # Use word-boundary matching to avoid substring false positives
    # (e.g., "metric" matching "parametric", "normal" matching "abnormal").
    key_terms = [t for t in expected_root.split() if len(t) > 3]
    terms_found = sum(1 for t in key_terms if _term_in_text(t, combined_text))
    term_match_ratio = terms_found / max(len(key_terms), 1)

    # Award points for root cause identification based on criteria
    criteria = rubric["criteria"]
    for criterion in criteria:
        desc = criterion["description"].lower()
        pts = criterion["points"]

        # First criterion is always the primary root cause identification
        if "identifies" in desc or "concludes" in desc:
            if term_match_ratio >= 0.5:
                earned += pts
                details.append(f"+{pts}: Root cause identified (match ratio {term_match_ratio:.0%})")
            else:
                details.append(f"+0: Root cause not identified (match ratio {term_match_ratio:.0%})")
        # Criteria about localization (e.g., "correctly localizes to Standard tier")
        elif "localizes" in desc or "concentrated" in desc or "attributes" in desc or "notes" in desc:
            # Check if the dominant segment is mentioned
            segment = hypothesis.get("segment", "")
            dimension = hypothesis.get("dimension", "")
            if segment and segment.lower() in combined_text:
                earned += pts
                details.append(f"+{pts}: Localized to {dimension}={segment}")
            elif "no significant" in expected_root and "no" in hypothesis_desc:
                # For false alarm case: "no significant movement" is correct
                earned += pts
                details.append(f"+{pts}: Correctly concludes no issue")
            else:
                details.append(f"+0: Localization missing")
        # Criteria about what NOT to attribute to.
        # NOTE: This checks the criterion description directly against the hypothesis,
        # NOT the must_not_do list. The must_not_do deductions are handled separately
        # in _check_must_not_do_violations to avoid double-counting penalties.
        elif "not" in desc or "does not" in desc:
            # Extract meaningful terms from the criterion description itself
            # e.g., "Does NOT attribute to AI features, connector, or seasonal"
            # -> check if hypothesis mentions "ai", "connector", "seasonal"
            wrong_terms = [
                t.lower() for t in desc.split()
                if len(t) > 3 and t.lower() not in (
                    "does", "not", "should", "attribute", "claim", "assign",
                    "this", "that", "with", "from", "have", "been",
                )
            ]
            attributed_wrong = any(
                _term_in_text(t, hypothesis_desc) for t in wrong_terms
            )
            if not attributed_wrong:
                earned += pts
                details.append(f"+{pts}: No wrong attribution detected in hypothesis")
            else:
                details.append(f"+0: Hypothesis may contain wrong attribution")
        else:
            # Default: partial credit based on overall match quality
            if term_match_ratio >= 0.3:
                earned += pts
                details.append(f"+{pts}: General criterion met")
            else:
                details.append(f"+0: General criterion not met")

    return {
        "dimension": "root_cause_accuracy",
        "earned": min(earned, max_points),
        "max": max_points,
        "details": details,
    }


def _score_confidence_calibration(
    spec: Dict[str, Any],
    diagnosis: Dict[str, Any],
    formatted: Dict[str, str],
) -> Dict[str, Any]:
    """Score the confidence_calibration dimension (25 points max).

    Checks if the confidence level is appropriate for the scenario
    and calibrated correctly (not over- or under-confident).

    Args:
        spec: Scoring spec dict.
        diagnosis: Raw diagnosis output dict.
        formatted: Formatted output dict.

    Returns:
        Dict with dimension name, points earned, max points, and details.
    """
    rubric = spec["rubric"]["confidence_calibration"]
    max_points = rubric["weight"]
    earned = 0
    details = []

    confidence = diagnosis.get("confidence", {})
    actual_level = confidence.get("level", "Unknown")
    expected_level = spec["output_quality"].get("confidence_level", "")
    severity = diagnosis.get("aggregate", {}).get("severity", "P2")
    report_text = formatted.get("short_report", "").lower()

    criteria = rubric["criteria"]
    for criterion in criteria:
        desc = criterion["description"].lower()
        pts = criterion["points"]

        # Criteria about severity classification
        if "severity" in desc or "p0" in desc or "p1" in desc:
            # Check if actual severity matches what the spec expects
            if "not" in desc and ("p0" in desc or "p1" in desc):
                # Must NOT assign P0/P1
                if severity not in ("P0", "P1"):
                    earned += pts
                    details.append(f"+{pts}: Correctly avoids P0/P1 severity")
                else:
                    details.append(f"+0: Incorrectly assigned {severity}")
            elif "p2" in desc or "normal" in desc:
                if severity in ("P2", "normal"):
                    earned += pts
                    details.append(f"+{pts}: Correct severity classification")
                else:
                    details.append(f"+0: Wrong severity: {severity}")
            else:
                # General severity check
                earned += pts
                details.append(f"+{pts}: Severity assessed")

        # Criteria about confidence level itself
        elif "confidence" in desc and ("high" in desc or "medium" in desc or "low" in desc):
            # Check if confidence matches expected
            level_ok = False
            if expected_level == "High" and actual_level == "High":
                level_ok = True
            elif expected_level == "Medium" and actual_level == "Medium":
                level_ok = True
            elif expected_level == "Medium_or_High" and actual_level in ("Medium", "High"):
                level_ok = True
            elif "not low" in desc.lower() and actual_level != "Low":
                level_ok = True
            elif actual_level.lower() in desc:
                level_ok = True

            if level_ok:
                earned += pts
                details.append(f"+{pts}: Confidence level {actual_level} matches expected")
            else:
                details.append(f"+0: Confidence {actual_level} doesn't match expected {expected_level}")

        # Criteria about hedging or uncertainty
        elif "hedge" in desc or "manufacture" in desc or "uncertainty" in desc:
            hedging_terms = ["possibly", "might be", "perhaps", "it's unclear", "may or may not"]
            has_hedging = any(term in report_text for term in hedging_terms)
            if not has_hedging:
                earned += pts
                details.append(f"+{pts}: No hedging detected")
            else:
                details.append(f"+0: Hedging language detected in output")

        # Criteria about explicit statements
        elif "explicitly" in desc or "states" in desc or "flags" in desc:
            # Check for specific content in report
            if "what" in desc and "downgrade" in desc:
                # "Provides what-would-downgrade condition"
                if confidence.get("would_downgrade_if") or confidence.get("would_upgrade_if"):
                    earned += pts
                    details.append(f"+{pts}: Upgrade/downgrade conditions stated")
                else:
                    details.append(f"+0: Missing upgrade/downgrade conditions")
            elif "mix" in desc:
                # "Flags mix-shift contribution percentage explicitly"
                if "mix" in report_text and "%" in report_text:
                    earned += pts
                    details.append(f"+{pts}: Mix-shift percentage flagged")
                else:
                    details.append(f"+0: Mix-shift percentage not flagged")
            elif "tradeoff" in desc or "trade" in desc:
                if "tradeoff" in report_text or "trade-off" in report_text or "trade off" in report_text:
                    earned += pts
                    details.append(f"+{pts}: Tradeoff acknowledged")
                else:
                    details.append(f"+0: Tradeoff not mentioned")
            elif "normal" in desc or "variation" in desc:
                if "normal" in report_text or "within" in report_text:
                    earned += pts
                    details.append(f"+{pts}: Normal variation stated")
                else:
                    details.append(f"+0: Normal variation not stated")
            else:
                # Default: check for explicit confidence statement
                if f"confidence: {actual_level.lower()}" in report_text or \
                   f"confidence: {actual_level}" in formatted.get("slack_message", "").lower():
                    earned += pts
                    details.append(f"+{pts}: Confidence explicitly stated")
                else:
                    details.append(f"+0: Confidence not explicitly stated")
        else:
            # Default: award if confidence is stated at all
            if actual_level != "Unknown":
                earned += pts
                details.append(f"+{pts}: Confidence dimension evaluated")
            else:
                details.append(f"+0: No confidence assessment")

    return {
        "dimension": "confidence_calibration",
        "earned": min(earned, max_points),
        "max": max_points,
        "details": details,
    }


def _score_investigation_completeness(
    spec: Dict[str, Any],
    diagnosis: Dict[str, Any],
    formatted: Dict[str, str],
) -> Dict[str, Any]:
    """Score the investigation_completeness dimension (20 points max).

    Checks whether the required dimensions were analyzed and the
    investigation was thorough (mix-shift, co-movement, etc.).

    Args:
        spec: Scoring spec dict.
        diagnosis: Raw diagnosis output dict.
        formatted: Formatted output dict.

    Returns:
        Dict with dimension name, points earned, max points, and details.
    """
    rubric = spec["rubric"]["investigation_completeness"]
    max_points = rubric["weight"]
    earned = 0
    details = []

    # What dimensions were actually decomposed?
    dimensional = diagnosis.get("dimensional_breakdown", {})
    decomposed_dims = set(dimensional.keys())
    required_dims = set(spec.get("must_check_dimensions", []))

    # Check mix-shift
    mix_shift = diagnosis.get("mix_shift", {})
    has_mix_shift = bool(mix_shift and mix_shift.get("mix_shift_contribution_pct") is not None)

    # Check validation checks
    checks = diagnosis.get("validation_checks", [])
    check_names = [c.get("check", "") for c in checks]

    criteria = rubric["criteria"]
    for criterion in criteria:
        desc = criterion["description"].lower()
        pts = criterion["points"]

        # Criteria about decomposition by specific dimensions
        if "decomposes" in desc or "segments" in desc or "decompose" in desc:
            # Check if required dimensions were analyzed
            found = required_dims.intersection(decomposed_dims)
            if found:
                earned += pts
                details.append(f"+{pts}: Decomposed by {', '.join(found)}")
            else:
                details.append(f"+0: Required dimensions not decomposed: {required_dims}")

        # Criteria about mix-shift analysis
        elif "mix-shift" in desc or "mix_shift" in desc:
            if has_mix_shift:
                earned += pts
                details.append(f"+{pts}: Mix-shift analysis performed")
            else:
                details.append(f"+0: Mix-shift analysis missing")

        # Criteria about checking specific things
        elif "checks" in desc or "check" in desc:
            # Count validation checks as investigation thoroughness
            if len(checks) >= 2:
                earned += pts
                details.append(f"+{pts}: {len(checks)} validation checks run")
            else:
                details.append(f"+0: Insufficient validation checks")

        # Criteria about co-movement or comparison
        elif "co-movement" in desc or "compares" in desc or "pattern" in desc:
            # Co-movement pattern check
            if any("co-movement" in str(c.get("detail", "")).lower() or
                   "pattern" in str(c.get("detail", "")).lower()
                   for c in checks):
                earned += pts
                details.append(f"+{pts}: Co-movement pattern checked")
            elif len(checks) >= 3:
                # If we have 3+ checks, we're being reasonably thorough
                earned += pts
                details.append(f"+{pts}: Sufficient investigation depth")
            else:
                details.append(f"+0: Co-movement not checked")

        # Criteria about data quality
        elif "data quality" in desc or ("data" in desc and "quality" in desc):
            has_data_check = any("logging" in c.get("check", "") or "data" in c.get("check", "")
                                for c in checks)
            if has_data_check or "logging_artifact" in check_names:
                earned += pts
                details.append(f"+{pts}: Data quality verified")
            else:
                details.append(f"+0: Data quality not checked")

        # Criteria about verifying per-segment stability
        elif "stable" in desc or "per-segment" in desc or "verifies" in desc:
            # Check if segments have baseline and current means
            has_segment_data = False
            for dim_data in dimensional.values():
                for seg in dim_data.get("segments", []):
                    if "baseline_mean" in seg and "current_mean" in seg:
                        has_segment_data = True
                        break
            if has_segment_data:
                earned += pts
                details.append(f"+{pts}: Per-segment data verified")
            else:
                details.append(f"+0: Per-segment verification missing")

        else:
            # Default: partial credit
            if len(checks) >= 2:
                earned += pts
                details.append(f"+{pts}: General investigation criterion met")
            else:
                details.append(f"+0: General investigation criterion not met")

    return {
        "dimension": "investigation_completeness",
        "earned": min(earned, max_points),
        "max": max_points,
        "details": details,
    }


def _score_actionability(
    spec: Dict[str, Any],
    diagnosis: Dict[str, Any],
    formatted: Dict[str, str],
) -> Dict[str, Any]:
    """Score the actionability dimension (15 points max).

    Checks whether the output has a TL;DR, actionable recommendations,
    and doesn't create unnecessary escalations.

    Args:
        spec: Scoring spec dict.
        diagnosis: Raw diagnosis output dict.
        formatted: Formatted output dict.

    Returns:
        Dict with dimension name, points earned, max points, and details.
    """
    rubric = spec["rubric"]["actionability"]
    max_points = rubric["weight"]
    earned = 0
    details = []

    action_items = diagnosis.get("action_items", [])
    slack_text = formatted.get("slack_message", "").lower()
    report_text = formatted.get("short_report", "").lower()
    combined = f"{slack_text} {report_text}"

    criteria = rubric["criteria"]
    for criterion in criteria:
        desc = criterion["description"].lower()
        pts = criterion["points"]

        # Criteria about unnecessary actions
        if "not" in desc and ("recommend" in desc or "create" in desc or "unnecessary" in desc):
            # For false alarm: should NOT create action items
            if spec["output_quality"].get("actionable_recommendation") is False:
                # Correct behavior: minimal or no escalation
                if len(action_items) <= 2:
                    earned += pts
                    details.append(f"+{pts}: Appropriately restrained on actions")
                else:
                    details.append(f"+0: Too many action items for a non-issue")
            else:
                # For real issues: check that rollback isn't recommended when inappropriate
                if "rollback" in desc:
                    if "rollback" not in combined:
                        earned += pts
                        details.append(f"+{pts}: No inappropriate rollback recommendation")
                    else:
                        details.append(f"+0: Inappropriate rollback recommended")
                else:
                    earned += pts
                    details.append(f"+{pts}: Appropriate action restraint")

        # Criteria about TL;DR
        elif "tl;dr" in desc or "tldr" in desc:
            if "tl;dr" in combined or "tldr" in combined or "tl:dr" in combined:
                earned += pts
                details.append(f"+{pts}: TL;DR present in output")
            else:
                details.append(f"+0: TL;DR missing from output")

        # Criteria about recommending investigation
        elif "recommend" in desc and ("investigat" in desc or "monitor" in desc):
            if action_items:
                earned += pts
                details.append(f"+{pts}: Actionable recommendations provided")
            elif spec["output_quality"].get("actionable_recommendation") is False:
                # No action needed is correct for false alarm
                earned += pts
                details.append(f"+{pts}: Correctly identified no action needed")
            else:
                details.append(f"+0: No actionable recommendations")

        # Criteria about action owners
        elif "owner" in desc:
            # Check if actions mention roles/teams
            has_owners = any(
                "team" in str(a).lower() or "lead" in str(a).lower() or
                "engineer" in str(a).lower() or "(" in str(a)
                for a in action_items
            )
            if has_owners or not action_items:
                earned += pts
                details.append(f"+{pts}: Action owners present")
            else:
                details.append(f"+0: Action owners missing")

        # Criteria about monitoring
        elif "monitoring" in desc or "continued" in desc:
            if "monitor" in combined or "continue" in combined:
                earned += pts
                details.append(f"+{pts}: Monitoring recommended")
            else:
                # Not penalizing if monitoring isn't needed
                earned += pts
                details.append(f"+{pts}: Monitoring criterion acceptable")

        else:
            # Default: give credit if there's any actionable content
            if action_items or spec["output_quality"].get("actionable_recommendation") is False:
                earned += pts
                details.append(f"+{pts}: General actionability criterion met")
            else:
                details.append(f"+0: General actionability criterion not met")

    return {
        "dimension": "actionability",
        "earned": min(earned, max_points),
        "max": max_points,
        "details": details,
    }


# ──────────────────────────────────────────────────
# Must-Not-Do Deduction
# ──────────────────────────────────────────────────

def _check_must_not_do_violations(
    spec: Dict[str, Any],
    diagnosis: Dict[str, Any],
    formatted: Dict[str, str],
) -> List[Dict[str, Any]]:
    """Check for must_not_do anti-pattern violations.

    Each violation deducts 10 points from the total score.
    This is a separate check from the rubric dimensions because
    anti-patterns are hard failures regardless of other criteria.

    Args:
        spec: Scoring spec dict with must_not_do list.
        diagnosis: Raw diagnosis output dict.
        formatted: Formatted output dict.

    Returns:
        List of violation dicts with rule name, reason, and deduction.
    """
    violations = []
    hypothesis_desc = diagnosis.get("primary_hypothesis", {}).get("description", "").lower()
    confidence_level = diagnosis.get("confidence", {}).get("level", "Unknown")
    severity = diagnosis.get("aggregate", {}).get("severity", "P2")
    report_text = formatted.get("short_report", "").lower()
    slack_text = formatted.get("slack_message", "").lower()
    combined = f"{hypothesis_desc} {report_text} {slack_text}"

    for anti_pattern in spec.get("must_not_do", []):
        if isinstance(anti_pattern, dict):
            for rule_name, reason in anti_pattern.items():
                violated = False

                # Check specific anti-pattern rules by name
                if "rollback" in rule_name and "rollback" in combined:
                    violated = True
                elif "regression" in rule_name and "regression" in hypothesis_desc:
                    violated = True
                elif "p0" in rule_name.lower() and severity == "P0":
                    violated = True
                elif "p0_or_p1" in rule_name.lower() and severity in ("P0", "P1"):
                    violated = True
                elif "incident" in rule_name and "incident" in combined:
                    violated = True
                elif "single_cause" in rule_name:
                    # For multi-cause scenario: penalize if High confidence AND
                    # the diagnosis doesn't acknowledge multiple causes.
                    # Just being High confidence is not a violation — the hypothesis
                    # must actually claim a single cause without mentioning others.
                    multi_cause_terms = ["both", "multiple", "overlap", "two", "several"]
                    mentions_multiple = any(
                        _term_in_text(t, hypothesis_desc) for t in multi_cause_terms
                    )
                    if "high" in confidence_level.lower() and not mentions_multiple:
                        violated = True
                elif "hedge" in rule_name:
                    hedging = ["possibly", "might be", "perhaps", "may or may not"]
                    if any(h in combined for h in hedging):
                        violated = True
                elif "manufacture" in rule_name and "cause" in rule_name:
                    # Manufacturing a root cause for normal fluctuation
                    # Check if the spec expects no significant movement
                    if spec["case"].get("archetype") == "false_alarm_restraint":
                        if hypothesis_desc and "no" not in hypothesis_desc:
                            violated = True
                elif "no_action" in rule_name or "recommend_no_action" in rule_name:
                    # Must NOT recommend no action when there IS a regression
                    if not diagnosis.get("action_items"):
                        violated = True
                elif "ignore" in rule_name or "miss" in rule_name:
                    # Check if the diagnosis skipped a required analysis.
                    # Look at must_check_dimensions and see if they appear
                    # in the dimensional_breakdown of the diagnosis.
                    required_dims = set(spec.get("must_check_dimensions", []))
                    decomposed_dims = set(
                        diagnosis.get("dimensional_breakdown", {}).keys()
                    )
                    missing_dims = required_dims - decomposed_dims
                    # Also check if specific terms from the rule are in the output
                    rule_terms = [t for t in rule_name.split("_") if len(t) > 2]
                    relevant_dim_missing = any(
                        any(_term_in_text(t, dim) for t in rule_terms)
                        for dim in missing_dims
                    )
                    if missing_dims and relevant_dim_missing:
                        violated = True

                if violated:
                    violations.append({
                        "rule": rule_name,
                        "reason": reason,
                        "deduction": 10,
                    })

    return violations


# ──────────────────────────────────────────────────
# Single Run Scorer
# ──────────────────────────────────────────────────

def score_single_run(
    spec: Dict[str, Any],
    diagnosis: Dict[str, Any],
    formatted: Dict[str, str],
) -> Dict[str, Any]:
    """Score a single diagnosis run against a scoring spec.

    This is the main scoring function. It evaluates each of the 4
    rubric dimensions, checks for must_not_do violations, and
    computes a total score with a GREEN/YELLOW/RED grade.

    Scoring logic:
    1. Score each of the 4 dimensions (max 100 points total)
    2. Deduct 10 points per must_not_do violation
    3. Floor at 0 (can't go negative)
    4. Grade: >= 80 = GREEN, >= 60 = YELLOW, < 60 = RED

    Args:
        spec: Scoring spec dict for this eval case.
        diagnosis: Raw diagnosis output from run_diagnosis().
        formatted: Formatted output dict from format_diagnosis_output().

    Returns:
        Dict with total_score, grade, per_dimension scores, and violations.
    """
    # Score each dimension
    dim_scores = [
        _score_root_cause_accuracy(spec, diagnosis, formatted),
        _score_confidence_calibration(spec, diagnosis, formatted),
        _score_investigation_completeness(spec, diagnosis, formatted),
        _score_actionability(spec, diagnosis, formatted),
    ]

    # Sum up the raw score from rubric dimensions (max 100)
    raw_score = sum(d["earned"] for d in dim_scores)

    # Check for must_not_do violations (each deducts 10 points)
    violations = _check_must_not_do_violations(spec, diagnosis, formatted)
    total_deduction = sum(v["deduction"] for v in violations)

    # Final score: raw minus deductions, floored at 0
    total_score = max(0, raw_score - total_deduction)

    # Grade based on thresholds from scoring spec
    pass_threshold = spec.get("scoring", {}).get("pass", 60)
    green_threshold = spec.get("scoring", {}).get("green", 80)

    if total_score >= green_threshold:
        grade = "GREEN"
    elif total_score >= pass_threshold:
        grade = "YELLOW"
    else:
        grade = "RED"

    return {
        "total_score": total_score,
        "raw_score": raw_score,
        "deductions": total_deduction,
        "grade": grade,
        "per_dimension": {d["dimension"]: d for d in dim_scores},
        "violations": violations,
    }


# ──────────────────────────────────────────────────
# 3-Run Aggregation
# ──────────────────────────────────────────────────

def aggregate_runs(
    run_results: List[Dict[str, Any]],
    pass_threshold: str,
) -> Dict[str, Any]:
    """Aggregate 3 run results into a single verdict using majority vote.

    The design doc specifies:
    - 3/3 GREEN => GREEN (reliable)
    - 2/3 GREEN => YELLOW (investigate variance)
    - 0-1/3 GREEN => RED (block)

    But each case can set its own pass_threshold:
    - "3/3 GREEN" = all 3 must be GREEN
    - "2/3 GREEN" = at least 2 must be GREEN

    Args:
        run_results: List of 3 score dicts from score_single_run().
        pass_threshold: String like "3/3 GREEN" or "2/3 GREEN".

    Returns:
        Dict with verdict (GREEN/YELLOW/RED), run scores, and stats.
    """
    green_count = sum(1 for r in run_results if r.get("grade") == "GREEN")
    scores = [r.get("total_score", 0) for r in run_results]

    # Parse the threshold: "N/3 GREEN" -> need N greens
    # Default: "3/3 GREEN" requires all 3 green
    required_greens = 3
    if pass_threshold.startswith("2/3"):
        required_greens = 2
    elif pass_threshold.startswith("1/3"):
        required_greens = 1

    # Determine verdict.
    # Design doc tiers (fixed): 3/3=reliable, 2/3=investigate, 0-1/3=block.
    # The per-case threshold adjusts where GREEN starts, but the doc's
    # 3-tier system sets the baseline for YELLOW vs RED.
    if green_count >= required_greens:
        verdict = "GREEN"
    elif green_count >= 2:
        # 2/3 GREEN is always at least YELLOW per the design doc
        verdict = "YELLOW"
    elif green_count == 1 and required_greens <= 2:
        # 1/3 is YELLOW only if the case threshold is lenient (2/3)
        verdict = "YELLOW"
    else:
        verdict = "RED"

    return {
        "verdict": verdict,
        "green_count": green_count,
        "required_greens": required_greens,
        "scores": scores,
        "avg_score": sum(scores) / max(len(scores), 1),
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
    }


# ──────────────────────────────────────────────────
# LLM-as-Judge Prompt Builder
# ──────────────────────────────────────────────────

def build_judge_prompt(
    spec: Dict[str, Any],
    diagnosis_output: str,
) -> str:
    """Build the LLM-as-judge evaluation prompt from a scoring spec.

    The design doc requires: "rubric baked verbatim into prompt."
    This function generates a structured prompt that a separate LLM
    can use to evaluate the diagnosis output.

    The prompt includes:
    1. Evaluation instructions
    2. The full rubric with criteria and points
    3. The must_find root cause
    4. The must_not_do anti-patterns
    5. The diagnosis output to evaluate
    6. Required JSON response format

    Args:
        spec: Scoring spec dict for this eval case.
        diagnosis_output: The formatted diagnosis output to evaluate.

    Returns:
        Complete evaluation prompt string.
    """
    case = spec["case"]
    rubric = spec["rubric"]
    must_find = spec["must_find"]
    must_not_do = spec.get("must_not_do", [])
    output_quality = spec.get("output_quality", {})

    # Build rubric section
    rubric_lines = []
    for dim_name, dim in rubric.items():
        rubric_lines.append(f"\n### {dim_name} ({dim['weight']} points)")
        for criterion in dim["criteria"]:
            rubric_lines.append(f"  - [{criterion['points']} pts] {criterion['description']}")
    rubric_text = "\n".join(rubric_lines)

    # Build must_not_do section
    anti_pattern_lines = []
    for anti in must_not_do:
        if isinstance(anti, dict):
            for rule, reason in anti.items():
                anti_pattern_lines.append(f"  - {rule}: {reason}")
        else:
            anti_pattern_lines.append(f"  - {anti}")
    anti_text = "\n".join(anti_pattern_lines)

    prompt = f"""You are an expert evaluator for an Enterprise Search metric diagnosis tool.

## Task
Evaluate the following diagnosis output for Case: "{case['name']}" (Scenario {case['scenario']}).
Purpose: {case['purpose']}

## Scoring Rubric (100 points total)
{rubric_text}

## Must Find
The diagnosis MUST identify this root cause (semantic match, not exact string):
  "{must_find['root_cause']}"

## Must NOT Do
The diagnosis must NOT violate these anti-patterns (each violation = -10 points):
{anti_text}

## Output Quality Checks
- Has TL;DR: {output_quality.get('has_tldr', True)}
- Confidence stated: {output_quality.get('confidence_stated', True)}
- Expected confidence level: {output_quality.get('confidence_level', 'N/A')}
- Actionable recommendation required: {output_quality.get('actionable_recommendation', True)}

## Diagnosis Output to Evaluate
---
{diagnosis_output}
---

## Instructions
1. Score each rubric dimension by checking each criterion (award points or 0)
2. Check for must_not_do violations (deduct 10 points each)
3. Check output quality requirements
4. Compute total score (0-100 scale)

## Required Response Format (JSON)
Respond with ONLY valid JSON in this exact format:
{{
  "root_cause_accuracy": {{"earned": <int>, "max": {rubric['root_cause_accuracy']['weight']}, "reasoning": "<str>"}},
  "confidence_calibration": {{"earned": <int>, "max": {rubric['confidence_calibration']['weight']}, "reasoning": "<str>"}},
  "investigation_completeness": {{"earned": <int>, "max": {rubric['investigation_completeness']['weight']}, "reasoning": "<str>"}},
  "actionability": {{"earned": <int>, "max": {rubric['actionability']['weight']}, "reasoning": "<str>"}},
  "violations": [<list of violated rule names>],
  "total_score": <int>,
  "grade": "<GREEN|YELLOW|RED>"
}}"""

    return prompt


# ──────────────────────────────────────────────────
# CLI Interface
# ──────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Run eval scoring on diagnosis output"
    )
    parser.add_argument(
        "--case", default=None,
        help="Specific scenario to evaluate (e.g., S4). Defaults to all."
    )
    parser.add_argument(
        "--diagnosis", default=None,
        help="Path to JSON file with diagnosis output to score"
    )
    parser.add_argument(
        "--list-cases", action="store_true",
        help="List all available eval cases and exit"
    )
    return parser.parse_args()


def main():
    """CLI entry point: load specs, score diagnosis, output results."""
    args = parse_args()

    # Load all scoring specs
    specs = load_scoring_specs()

    if args.list_cases:
        for spec in specs:
            case = spec["case"]
            print(f"  {case['scenario']}: {case['name']} ({case['pass_threshold']})")
        return

    # Filter to specific case if requested
    if args.case:
        specs = [s for s in specs if s["case"]["scenario"] == args.case]
        if not specs:
            print(json.dumps({"error": f"No scoring spec found for scenario {args.case}"}))
            sys.exit(1)

    # If a diagnosis file is provided, score it
    if args.diagnosis:
        diag_path = Path(args.diagnosis)
        if not diag_path.exists():
            print(json.dumps({"error": f"File not found: {args.diagnosis}"}))
            sys.exit(1)

        with open(diag_path) as f:
            diagnosis = json.load(f)

        # Generate formatted output for scoring
        # Import formatter here to avoid circular dependency at module level
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tools.formatter import format_diagnosis_output
        formatted = format_diagnosis_output(diagnosis)

        results = {}
        for spec in specs:
            score = score_single_run(spec, diagnosis, formatted)
            results[spec["case"]["scenario"]] = score

        print(json.dumps(results, indent=2))
    else:
        # No diagnosis file — just list what would be evaluated
        print(json.dumps({
            "mode": "dry_run",
            "cases": [
                {
                    "scenario": s["case"]["scenario"],
                    "name": s["case"]["name"],
                    "pass_threshold": s["case"]["pass_threshold"],
                }
                for s in specs
            ],
        }, indent=2))


if __name__ == "__main__":
    main()
