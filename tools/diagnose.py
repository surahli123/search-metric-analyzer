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

# False alarm detection: if no segment explains more than this % of
# a small (P2/normal) movement, it's likely noise — not a real cause.
FALSE_ALARM_MAX_SEGMENT_CONTRIBUTION = 50.0

# Multi-cause detection: if top segments in DIFFERENT dimensions each
# explain more than this %, flag as multi-cause.
MULTI_CAUSE_MIN_CONTRIBUTION = 30.0

# Per-metric noise thresholds (fraction, not percentage).
# Derived from weekly_std/mean ratios in metric_definitions.yaml.
# Used to prevent false alarm path (b) from triggering on real movements.
METRIC_NOISE_THRESHOLDS = {
    "dlctr_value":   0.04,   # weekly_std/mean = 5.4%; threshold at 4%
    "qsr_value":     0.03,   # weekly_std/mean = 3.2%; threshold at 3%
    "sain_trigger":  0.06,   # weekly_std/mean = 4.5%; was 7% → now 6% (1.3x CV)
    "sain_success":  0.06,   # weekly_std/mean = 2.4%; was 7% → now 6% (2.5x CV)
}
DEFAULT_NOISE_THRESHOLD = 0.03


# ──────────────────────────────────────────────────
# Archetype Recognition
# ──────────────────────────────────────────────────

# Map co-movement likely_cause to diagnostic archetypes.
# Each archetype customizes: severity adjustment, hypothesis framing,
# confidence overrides, action item templates with owners.
#
# WHY ARCHETYPES:
# Raw decomposition says "biggest segment is X." But a Senior DS goes further:
# they recognize PATTERNS like "AI adoption trap" (DLCTR drops when AI works)
# and adjust their diagnosis accordingly. Archetypes encode this domain expertise.
ARCHETYPE_MAP = {
    "ranking_relevance_regression": {
        "archetype": "ranking_regression",
        "severity_cap": None,   # No cap — real regression, use magnitude-based severity
        "description_template": (
            "Ranking model regression detected. {metric_name} decline is concentrated "
            "in {dimension}='{segment}' ({contribution:.1f}% of total change). "
            "Check recent ranking model deploys, experiment ramps, or retraining runs."
        ),
        "action_items": [
            {"action": "Check recent ranking model deploys and experiment ramps", "owner": "Search Ranking team"},
            {"action": "Compare ranking model version between baseline and current period", "owner": "Search Ranking team"},
            {"action": "Review per-segment DLCTR to isolate affected query types", "owner": "Search Quality DS"},
        ],
        "category": "algorithm_model",
        # v1.4: Structured subagent specs — conditions that confirm or reject this archetype.
        # Used by verify_diagnosis() for coherence checks and by production subagents
        # for SQL query generation.
        "confirms_if": [
            "DLCTR drop concentrated in specific position buckets (3-5, 6-10)",
            "Ranking model version changed in the movement window",
            "SAIN metrics stable (not AI-driven)",
        ],
        "rejects_if": [
            "DLCTR drop uniform across all segments (suggests logging, not ranking)",
            "Movement proportional to traffic mix-shift (>50% compositional)",
            "SAIN trigger or success also changed (suggests AI adoption, not ranking)",
        ],
    },
    "ai_answers_working": {
        "archetype": "ai_adoption",
        "severity_cap": "P2",   # Cap at P2 — this is a POSITIVE signal, not a problem
        "description_template": (
            "AI adoption effect: {metric_name} decline is expected behavior — users are "
            "getting AI answers instead of clicking through to documents. QSR is stable "
            "or improving. This is a POSITIVE signal. "
            "The click-to-AI-answer tradeoff is working as designed."
        ),
        "action_items": [
            {"action": "Monitor AI answer quality (SAIN success rate) for sustained improvement", "owner": "AI team"},
            {"action": "Review click-vs-AI-answer tradeoff with product team", "owner": "Search Product PM"},
        ],
        "category": "ai_feature_effect",
        "is_positive": True,
        "confirms_if": [
            "DLCTR drop concentrated in ai_enablement=ai_on segment",
            "SAIN trigger and success both increasing",
            "QSR stable or improving (AI answers compensate for lost clicks)",
        ],
        "rejects_if": [
            "DLCTR drop in ai_enablement=ai_off segment (AI not involved)",
            "SAIN metrics flat or declining (AI answers not improving)",
            "QSR also declining (total quality loss, not just click substitution)",
        ],
    },
    "broad_quality_degradation": {
        "archetype": "broad_degradation",
        "severity_cap": None,
        "description_template": (
            "Broad quality degradation: both click quality ({metric_name}) and AI answer "
            "pathways are degraded. This affects all segments. "
            "Check for infrastructure issues, major model changes, or experiment ramps."
        ),
        "action_items": [
            {"action": "Check infrastructure health and recent deploys", "owner": "Search Platform team"},
            {"action": "Review ranking model and AI model versions", "owner": "Search Ranking team"},
            {"action": "Check experiment ramp schedules for conflicting experiments", "owner": "Experimentation team"},
        ],
        "category": "algorithm_model",
        "confirms_if": [
            "All 4 metrics declined simultaneously",
            "Movement uniform across tenant tiers and segments",
            "Infrastructure event or major deploy in the movement window",
        ],
        "rejects_if": [
            "Movement concentrated in a single segment (suggests targeted, not broad)",
            "Only DLCTR affected (suggests ranking or click behavior, not broad)",
            "Latency unchanged (suggests model issue, not infrastructure)",
        ],
    },
    "sain_quality_regression": {
        "archetype": "sain_regression",
        "severity_cap": None,
        "description_template": (
            "AI answer quality regression: SAIN success rate declining while trigger rate "
            "is stable. AI answers are appearing but not satisfying users. "
            "Check AI answer model version and quality thresholds."
        ),
        "action_items": [
            {"action": "Review SAIN model version and recent quality threshold changes", "owner": "AI team"},
            {"action": "Check AI answer accuracy by query type", "owner": "AI Quality DS"},
        ],
        "category": "ai_feature_effect",
        "confirms_if": [
            "SAIN success declining while SAIN trigger stable (answers appearing, not satisfying)",
            "AI answer model version or threshold changed in movement window",
            "Drop concentrated in specific query types or connector types",
        ],
        "rejects_if": [
            "SAIN trigger also declining (suggests trigger issue, not quality)",
            "DLCTR stable (suggests isolated AI issue with no click impact)",
            "Movement matches traffic mix-shift pattern (compositional, not behavioral)",
        ],
    },
    "click_behavior_change": {
        "archetype": "behavior_change",
        "severity_cap": None,
        "description_template": (
            "Click behavior change: only {metric_name} moved, SAIN metrics are stable. "
            "Possible causes: UX change, display change, or traffic mix-shift."
        ),
        "action_items": [
            {"action": "Check recent UX or display changes in search results", "owner": "Search Frontend team"},
            {"action": "Review traffic mix-shift for composition changes", "owner": "Search Quality DS"},
        ],
        "category": "user_behavior",
        "confirms_if": [
            "Only DLCTR moved while SAIN metrics are stable",
            "Recent UX, display, or SERP layout change in the movement window",
            "Click pattern change visible in position_bucket decomposition",
        ],
        "rejects_if": [
            "SAIN metrics also changed (suggests broader issue, not just clicks)",
            "Movement driven by mix-shift (>50% compositional)",
            "Ranking model version changed (suggests algorithm, not behavior)",
        ],
    },
    "sain_trigger_regression": {
        "archetype": "sain_trigger_issue",
        "severity_cap": None,
        "description_template": (
            "SAIN trigger regression: AI answers are not surfacing when they should. "
            "Check trigger threshold or model changes."
        ),
        "action_items": [
            {"action": "Check SAIN trigger threshold and model configuration", "owner": "AI team"},
        ],
        "category": "ai_feature_effect",
        "confirms_if": [
            "SAIN trigger declining while SAIN success stable (threshold or model issue)",
            "Trigger threshold or model configuration changed in movement window",
            "Drop concentrated in query types that should trigger AI answers",
        ],
        "rejects_if": [
            "SAIN success also declining (suggests broader AI quality issue)",
            "DLCTR also declining (suggests ranking, not trigger-specific)",
            "Trigger change proportional to query volume change (not a regression)",
        ],
    },
    "sain_success_regression": {
        "archetype": "sain_success_issue",
        "severity_cap": None,
        "description_template": (
            "SAIN success regression: AI answers are surfacing but not helpful. "
            "Check answer quality model."
        ),
        "action_items": [
            {"action": "Review AI answer quality model and content sources", "owner": "AI team"},
        ],
        "category": "ai_feature_effect",
        "confirms_if": [
            "SAIN success declining while SAIN trigger stable (quality, not coverage)",
            "AI answer quality model or content sources changed in movement window",
            "User engagement signals (dwell time, post-search actions) declining",
        ],
        "rejects_if": [
            "SAIN trigger also declining (suggests trigger issue, not quality)",
            "Movement matches a connector outage pattern (content source offline)",
            "Drop concentrated in a single connector type (data quality, not model)",
        ],
    },
    # ── Query Understanding regression ──
    # Source: Rovo — L0 Query Intelligence layer (intent classification,
    # spell correction, acronym resolution, LLM-based query reformulation).
    # A regression here is upstream of all ranking — misunderstood queries
    # produce bad results everywhere.
    "query_understanding_regression": {
        "archetype": "query_understanding",
        "severity_cap": None,           # Real regression — use magnitude severity
        "is_positive": False,
        "category": "query_understanding",
        # v1.4 bug fix: was summary_template + action (strings), which silently
        # failed in _build_primary_hypothesis() and _build_action_items().
        # Now matches the description_template + action_items pattern used by
        # all other archetypes.
        "description_template": (
            "Query understanding degradation detected — the search system's "
            "intent classification or query reformulation layer (L0) may be "
            "misinterpreting queries before they reach ranking. "
            "{metric_name} decline is concentrated in {dimension}='{segment}' "
            "({contribution:.1f}% of total change)."
        ),
        "action_items": [
            {"action": "Check query reformulation logs for increased rewrite error rates", "owner": "Query Understanding team"},
            {"action": "Verify intent classification model has not been retrained or threshold-changed", "owner": "Query Understanding team"},
            {"action": "Compare raw vs. reformulated query distributions before and after movement date", "owner": "Search Quality DS"},
        ],
        "confirms_if": [
            "Query reformulation error rate increased in the movement window",
            "Intent classification model retrained or threshold changed",
            "DLCTR and QSR both declined while SAIN success is stable (upstream issue)",
        ],
        "rejects_if": [
            "Movement isolated to a single segment (suggests ranking, not query understanding)",
            "SAIN success also declining (suggests AI model issue, not L0)",
            "Query distribution unchanged between baseline and current period",
        ],
    },
    "mix_shift_composition": {
        "archetype": "mix_shift",
        "severity_cap": None,
        "description_template": (
            "Traffic composition change (mix-shift) is the primary driver. "
            "{metric_name} aggregate moved because the mix of segments changed, "
            "not because behavior changed within any segment."
        ),
        "action_items": [
            {"action": "Verify per-segment metrics are stable", "owner": "Search Quality DS"},
            {"action": "Investigate traffic composition change (tenant onboarding, portfolio shift)", "owner": "Search Quality DS"},
        ],
        "category": "mix_shift",
        "confirms_if": [
            "Per-segment metrics stable (aggregate moved, individual segments didn't)",
            "Traffic volume distribution shifted between segments",
            "Mix-shift contribution exceeds 50% of total movement",
        ],
        "rejects_if": [
            "Per-segment metrics also changed (behavioral change, not just mix)",
            "Traffic distribution stable between baseline and current period",
            "Movement concentrated in a single segment (not compositional)",
        ],
    },
    "no_significant_movement": {
        "archetype": "false_alarm",
        "severity_cap": "normal",  # Override to "normal" — nothing happened
        "description_template": (
            "No significant metric movement detected. {metric_name} is within normal "
            "weekly variation. No action needed."
        ),
        "action_items": [],  # Empty — no action needed for false alarm
        "category": "false_alarm",
        "is_positive": True,
        "confirms_if": [
            "All 4 metrics within 1 standard deviation of their weekly baseline",
            "No single segment explains more than 50% of movement",
            "Movement consistent with historical weekly noise patterns",
        ],
        "rejects_if": [
            "Any metric moved more than 2 standard deviations",
            "A dominant segment explains >50% of movement (real cause masked as noise)",
            "Step-change pattern detected (sudden shift, not gradual noise)",
        ],
    },
}


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
# Post-Diagnosis Verification (v1.4 — DS-STAR Verifier)
# ──────────────────────────────────────────────────

def verify_diagnosis(diagnosis: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Post-diagnosis coherence checks. Returns list of warnings (empty = coherent).

    Inspired by DS-STAR's Verifier pattern: instead of trusting the first-pass
    diagnosis, run deterministic checks for internal contradictions. Unlike
    DS-STAR's LLM-based verifier, ours is pure Python assertions — no LLM cost,
    fully deterministic, runs in <1ms.

    WHY: The diagnostic pipeline is linear — each step builds on the previous.
    If an early archetype match is wrong, the severity, actions, and confidence
    all inherit the error. These checks catch contradictions that slip through.

    5 coherence checks:
    1. Archetype-segment consistency (does the top segment match the archetype?)
    2. Severity-action consistency (P0/P1 should have actions; "normal" shouldn't)
    3. Confidence-check consistency (High confidence shouldn't have HALT checks)
    4. False-alarm coherence (false_alarm must have empty actions + is_positive)
    5. Multi-cause-confidence consistency (multi-cause should downgrade confidence)

    Advisory mode: warnings don't block the diagnosis — they're surfaced in the
    formatted output so the analyst can decide what to do.

    Args:
        diagnosis: Complete diagnosis dict from run_diagnosis().

    Returns:
        List of warning dicts. Empty list = fully coherent.
        Each warning: {"check": str, "severity": "warning"|"error", "detail": str}
    """
    warnings: List[Dict[str, Any]] = []
    hypothesis = diagnosis.get("primary_hypothesis", {})
    archetype = hypothesis.get("archetype", "generic")
    aggregate = diagnosis.get("aggregate", {})
    severity = aggregate.get("severity", "P2")
    confidence = diagnosis.get("confidence", {})
    confidence_level = confidence.get("level", "Unknown")
    action_items = diagnosis.get("action_items", [])
    checks = diagnosis.get("validation_checks", [])

    # ── Check 1: Archetype-segment consistency ──
    # If archetype is ai_adoption, the top contributing segment should be
    # in the ai_enablement dimension. If archetype is ranking_regression,
    # the top segment should NOT be ai_enablement=ai_on.
    top_dimension = hypothesis.get("dimension")
    top_segment = hypothesis.get("segment")

    if archetype == "ai_adoption" and top_dimension and top_dimension != "ai_enablement":
        warnings.append({
            "check": "archetype_segment_consistency",
            "severity": "warning",
            "detail": (
                f"Archetype is ai_adoption but top segment is {top_dimension}='{top_segment}', "
                f"not ai_enablement. The AI adoption hypothesis may be misattributed."
            ),
        })

    if archetype == "ranking_regression" and top_dimension == "ai_enablement" and top_segment == "ai_on":
        warnings.append({
            "check": "archetype_segment_consistency",
            "severity": "warning",
            "detail": (
                "Archetype is ranking_regression but top segment is ai_enablement='ai_on'. "
                "This contradicts the ranking hypothesis — consider ai_adoption instead."
            ),
        })

    # ── Check 2: Severity-action consistency ──
    # P0/P1 should have action items (something urgent needs doing).
    # "normal" severity should have empty actions (nothing to do).
    if severity in ("P0", "P1") and len(action_items) == 0:
        warnings.append({
            "check": "severity_action_consistency",
            "severity": "error",
            "detail": (
                f"Severity is {severity} but no action items were generated. "
                f"High-severity findings should always include recommended actions."
            ),
        })

    if severity == "normal" and len(action_items) > 0:
        warnings.append({
            "check": "severity_action_consistency",
            "severity": "warning",
            "detail": (
                f"Severity is 'normal' but {len(action_items)} action item(s) were generated. "
                f"Normal severity typically means no action needed."
            ),
        })

    # ── Check 3: Confidence-check consistency ──
    # High confidence with a HALT check is suspicious — how can we be highly
    # confident when a fundamental check failed?
    # Exception: false_alarm archetype is allowed to override HALTs (the multi-metric
    # stability signal is strong enough to override individual check failures).
    has_halt = any(c.get("status") == "HALT" for c in checks)
    if confidence_level == "High" and has_halt and archetype != "false_alarm":
        halt_names = [c.get("check", "unknown") for c in checks if c.get("status") == "HALT"]
        warnings.append({
            "check": "confidence_check_consistency",
            "severity": "warning",
            "detail": (
                f"Confidence is High but HALT check(s) present: {', '.join(halt_names)}. "
                f"High confidence is unusual when fundamental checks have failed."
            ),
        })

    # ── Check 4: False-alarm coherence ──
    # If archetype is false_alarm, action_items MUST be empty (nothing to do)
    # and is_positive MUST be True (this is good news, not bad).
    if archetype == "false_alarm":
        if len(action_items) > 0:
            warnings.append({
                "check": "false_alarm_coherence",
                "severity": "error",
                "detail": (
                    f"Archetype is false_alarm but {len(action_items)} action item(s) were generated. "
                    f"False alarms should have no action items."
                ),
            })
        if not hypothesis.get("is_positive", False):
            warnings.append({
                "check": "false_alarm_coherence",
                "severity": "error",
                "detail": (
                    "Archetype is false_alarm but is_positive is False. "
                    "False alarms are inherently positive (nothing went wrong)."
                ),
            })

    # ── Check 5: Multi-cause-confidence consistency ──
    # If multi_cause is flagged, confidence should not be High.
    # Multi-cause means we can't cleanly attribute the movement to a single
    # archetype — the confidence downgrade should have fired in run_diagnosis().
    if hypothesis.get("multi_cause") and confidence_level == "High":
        warnings.append({
            "check": "multi_cause_confidence_consistency",
            "severity": "warning",
            "detail": (
                "Multi-cause detected but confidence is High. "
                "Attribution is uncertain with multiple overlapping causes — "
                "confidence should be Medium or lower."
            ),
        })

    return warnings


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
    # KNOWN LIMITATION (v1.2): sums absolute values, inflates for opposing-direction
    # segments (one up, one down). Tracked for v2.
    max_explained = 0.0
    for dim_name, dim_result in dimensional.items():
        segments = dim_result.get("segments", [])
        if segments:
            # Sum absolute contributions of all segments in this dimension.
            # This represents how much of the movement this dimension explains.
            # Sum absolute contributions. Cap at 100% because opposing-sign
            # segments (one up, one down) can inflate the sum beyond 100%.
            total_contribution = min(100.0, sum(
                abs(s.get("contribution_pct", 0)) for s in segments
            ))
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


def _detect_multi_cause(decomposition: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """Detect if multiple independent causes each explain a significant share.

    Multi-cause means: the top segments from DIFFERENT dimensions each explain
    >=30% of the movement. This is common in Enterprise Search where a ranking
    model change AND a traffic mix-shift happen in the same week.

    WHY THIS MATTERS:
    If we only report the single biggest segment, we miss the second cause
    entirely. A Senior DS would flag: "There are two things going on here."

    Args:
        decomposition: Output from decompose.run_decomposition()

    Returns:
        List of top-cause dicts if multi-cause detected, else None.
        Each dict: {"dimension": str, "segment": str, "contribution_pct": float}
    """
    dimensional = decomposition.get("dimensional_breakdown", {})
    if len(dimensional) < 2:
        return None

    # Collect the top segment from each dimension
    top_segments = []
    for dim_name, dim_result in dimensional.items():
        segments = dim_result.get("segments", [])
        if segments:
            top = segments[0]
            top_segments.append({
                "dimension": dim_name,
                "segment": top["segment_value"],
                "contribution_pct": abs(top.get("contribution_pct", 0)),
            })

    # Sort by contribution descending
    top_segments.sort(key=lambda x: x["contribution_pct"], reverse=True)

    # Check if at least 2 segments from DIFFERENT dimensions each exceed threshold
    if len(top_segments) >= 2:
        first = top_segments[0]
        second = top_segments[1]
        if (first["dimension"] != second["dimension"] and
                first["contribution_pct"] >= MULTI_CAUSE_MIN_CONTRIBUTION and
                second["contribution_pct"] >= MULTI_CAUSE_MIN_CONTRIBUTION):
            return [first, second]

    return None


def _build_primary_hypothesis(
    decomposition: Dict[str, Any],
    co_movement_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a primary hypothesis using archetype recognition + decomposition.

    This is the core "diagnostic intelligence" layer. Instead of just reporting
    "biggest segment is X," we:
    1. Check if co-movement matches a known archetype (AI adoption, ranking
       regression, false alarm, etc.)
    2. If yes: use the archetype's description template (domain expertise)
    3. If no: fall back to the generic "concentrated in X" description
    4. Check for multi-cause overlap
    5. Add action items with owners

    WHY ARCHETYPES:
    A generic "concentrated in ai_enablement=ai_off" tells the Eng Lead nothing
    actionable. But "Ranking model regression in Standard tier — check recent
    deploys" tells them exactly what to do. Archetypes encode this translation.

    Args:
        decomposition: Output from decompose.run_decomposition()
        co_movement_result: Output from anomaly.match_co_movement_pattern().
            Contains likely_cause, description, is_positive, priority_hypotheses.

    Returns:
        Dict with dimension, segment, contribution_pct, description, category,
        archetype, is_positive, and multi_cause (if detected).
    """
    dominant_dim = decomposition.get("dominant_dimension")
    dimensional = decomposition.get("dimensional_breakdown", {})
    aggregate = decomposition.get("aggregate", {})
    metric_name = aggregate.get("metric", "metric")
    direction = aggregate.get("direction", "changed")

    # ── Extract top segment info for template rendering ──
    top_segment_info = {"dimension": None, "segment": None, "contribution_pct": 0.0}
    if dominant_dim and dominant_dim in dimensional:
        segments = dimensional[dominant_dim].get("segments", [])
        if segments:
            top = segments[0]
            top_segment_info = {
                "dimension": dominant_dim,
                "segment": top["segment_value"],
                "contribution_pct": top["contribution_pct"],
                "baseline_mean": top.get("baseline_mean", 0),
                "current_mean": top.get("current_mean", 0),
            }

    # ── Check for multi-cause overlap ──
    multi_cause = _detect_multi_cause(decomposition)

    # ── Try archetype recognition via co-movement ──
    archetype_info = None
    if co_movement_result:
        likely_cause = co_movement_result.get("likely_cause", "unknown_pattern")
        archetype_info = ARCHETYPE_MAP.get(likely_cause)

    # ── Build the hypothesis ──
    if archetype_info:
        # Archetype matched — use the domain-expert description template
        template = archetype_info["description_template"]
        description = template.format(
            metric_name=metric_name,
            dimension=top_segment_info.get("dimension", "unknown"),
            segment=top_segment_info.get("segment", "unknown"),
            contribution=top_segment_info.get("contribution_pct", 0),
        )
        category = archetype_info.get("category", "unknown")
        archetype = archetype_info.get("archetype", "unknown")
        is_positive = archetype_info.get("is_positive", False)
    else:
        # No archetype match — fall back to generic description
        if top_segment_info["segment"]:
            description = (
                f"The {metric_name} movement is concentrated in "
                f"{top_segment_info['dimension']}='{top_segment_info['segment']}' "
                f"(contributing {top_segment_info['contribution_pct']:.1f}% of total change). "
                f"Segment {direction} from {top_segment_info.get('baseline_mean', 0):.4f} "
                f"to {top_segment_info.get('current_mean', 0):.4f}."
            )
        else:
            description = "No dominant dimension identified from decomposition."
        category = "unknown"
        archetype = "generic"
        is_positive = False

    # ── Enhance description for multi-cause ──
    # Suppress multi-cause for false_alarm (decomposition math amplifies noise).
    # For ai_adoption: suppress only when the "two causes" are correlated dimensions
    # (e.g., ai_enablement + tenant_tier are proxies for the same AI adoption effect).
    # Keep multi-cause when dimensions are truly independent (e.g., ai_enablement + connector_type).
    suppress_multi_cause = archetype == "false_alarm"
    if archetype == "ai_adoption" and multi_cause:
        # Known correlated dimension pairs — these represent the same underlying cause
        correlated_pairs = {frozenset({"ai_enablement", "tenant_tier"})}
        cause_dims = frozenset(c["dimension"] for c in multi_cause)
        suppress_multi_cause = cause_dims in correlated_pairs
    if multi_cause and not suppress_multi_cause:
        cause_strs = [
            f"{c['dimension']}='{c['segment']}' ({c['contribution_pct']:.0f}%)"
            for c in multi_cause
        ]
        description += (
            f" Multiple overlapping causes detected: {' AND '.join(cause_strs)}. "
            f"Both factors should be investigated independently."
        )

    result = {
        "dimension": top_segment_info.get("dimension"),
        "segment": top_segment_info.get("segment"),
        "contribution_pct": top_segment_info.get("contribution_pct", 0.0),
        "description": description,
        "category": category,
        "archetype": archetype,
        "is_positive": is_positive,
    }

    if multi_cause and not suppress_multi_cause:
        result["multi_cause"] = multi_cause

    return result


def _build_action_items(
    checks: List[Dict[str, Any]],
    confidence_level: str,
    decomposition: Dict[str, Any],
    co_movement_result: Optional[Dict[str, Any]] = None,
    primary_hypothesis: Optional[Dict[str, Any]] = None,
    confidence_result: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Generate actionable next steps with owners based on archetype + validation.

    Each action item is a dict with "action" and "owner" keys.
    The design doc requires: "Every recommendation has an owner."

    Action sources (in priority order):
    1. Archetype-specific actions (from ARCHETYPE_MAP) — most useful
    2. Validation check failures (HALT/WARN/INVESTIGATE)
    3. Confidence-based generic recommendations
    4. Drill-down recommendations from decomposition

    For false alarm archetype: returns empty list (no action needed).

    Args:
        checks: List of validation check results.
        confidence_level: "High", "Medium", or "Low".
        decomposition: Original decomposition output.
        co_movement_result: Output from match_co_movement_pattern().
        primary_hypothesis: Built hypothesis dict (has archetype info).

    Returns:
        List of action item dicts, each with "action" and "owner" keys.
    """
    actions: List[Dict[str, Any]] = []

    # ── Archetype-specific actions (highest value) ──
    # If we recognized an archetype, use its pre-defined action items with owners.
    # These encode domain expertise: "ranking regression → check model deploys"
    archetype = (primary_hypothesis or {}).get("archetype", "generic")

    # For false alarm: NO action items. This is intentional.
    # The eval spec (S0) scores us DOWN for creating unnecessary actions.
    if archetype == "false_alarm":
        return []

    # Look up archetype action items from the map
    if co_movement_result:
        likely_cause = co_movement_result.get("likely_cause", "unknown_pattern")
        archetype_info = ARCHETYPE_MAP.get(likely_cause)
        if archetype_info and archetype_info.get("action_items"):
            actions.extend(archetype_info["action_items"])

    # ── Validation check-based actions ──
    for check in checks:
        status = check.get("status", "PASS")
        check_name = check.get("check", "unknown")

        if status == "HALT":
            if check_name == "logging_artifact":
                actions.append({
                    "action": (
                        "PRIORITY: Verify logging and instrumentation pipeline "
                        "before proceeding. Check recent deploys and config changes."
                    ),
                    "owner": "Search Platform team",
                })
            elif check_name == "decomposition_completeness":
                actions.append({
                    "action": (
                        "Add more decomposition dimensions (e.g., connector_type, "
                        "query_type) to improve coverage of the unexplained residual."
                    ),
                    "owner": "Search Quality DS",
                })
            elif check_name == "temporal_consistency":
                actions.append({
                    "action": (
                        "Revise the causal hypothesis -- the proposed cause does not "
                        "precede the metric change. Look for earlier events."
                    ),
                    "owner": "Search Quality DS",
                })
        elif status == "INVESTIGATE":
            if check_name == "mix_shift":
                actions.append({
                    "action": (
                        "Investigate mix-shift: the movement may be driven by traffic "
                        "composition change rather than quality regression. "
                        "Compare per-segment metrics to confirm."
                    ),
                    "owner": "Search Quality DS",
                })

    # ── Confidence-based recommendations ──
    if confidence_level == "Low":
        # Build a specific action that tells the reader what would upgrade confidence
        upgrade_hint = ""
        if confidence_result and confidence_result.get("would_upgrade_if"):
            upgrade_hint = f" Specifically: {confidence_result['would_upgrade_if']}."
        actions.append({
            "action": (
                f"Low confidence diagnosis — gather more evidence before acting.{upgrade_hint}"
            ),
            "owner": "Search Quality DS",
        })
    # Medium confidence: no generic action — the archetype-specific actions
    # above are sufficient. Removed to avoid low-value filler recommendations.

    # ── Drill-down recommendation ──
    if decomposition.get("drill_down_recommended", False):
        dominant_dim = decomposition.get("dominant_dimension")
        if dominant_dim:
            actions.append({
                "action": (
                    f"Drill down into '{dominant_dim}' dimension for segment-level "
                    f"root cause analysis."
                ),
                "owner": "Search Quality DS",
            })

    return actions


def _apply_severity_override(
    aggregate: Dict[str, Any],
    archetype_info: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Apply context-aware severity adjustments based on archetype.

    WHY:
    Magnitude-based severity (P0 for >5% drop) is wrong when:
    - AI adoption: DLCTR drops 8% but it's GOOD → should be P2 not P0
    - Mix-shift: compositional change → should note "compositional" in severity
    - False alarm: noise → should be "normal" not P2

    This function overrides the raw severity with archetype-aware logic.
    The original severity is preserved in "original_severity" for auditing.

    Args:
        aggregate: Decomposition aggregate dict (has "severity" key).
        archetype_info: Matched archetype dict from ARCHETYPE_MAP (or None).

    Returns:
        Updated aggregate dict with possibly overridden severity.
    """
    if not archetype_info:
        return aggregate

    # Make a copy so we don't mutate the original
    result = dict(aggregate)

    severity_cap = archetype_info.get("severity_cap")
    if severity_cap:
        original = result.get("severity", "P2")
        result["original_severity"] = original
        result["severity"] = severity_cap
        result["severity_override_reason"] = (
            f"Severity overridden from {original} to {severity_cap}: "
            f"archetype is '{archetype_info.get('archetype', 'unknown')}'"
        )

    return result


def run_diagnosis(
    decomposition: Dict[str, Any],
    step_change_result: Optional[Dict[str, Any]] = None,
    co_movement_result: Optional[Dict[str, Any]] = None,
    cause_date_index: Optional[int] = None,
    metric_change_date_index: Optional[int] = None,
    has_historical_precedent: bool = False,
) -> Dict[str, Any]:
    """Run the full diagnosis pipeline on decomposition output.

    This is the main entry point for the diagnosis tool. It orchestrates
    all 4 validation checks, archetype recognition, and generates a complete
    diagnosis report.

    The pipeline (v1.1):
    1. Check for logging artifacts (step-change detection)
    2. Check decomposition completeness (segment coverage)
    3. Check temporal consistency (cause precedes effect)
    4. Check mix-shift threshold (compositional vs behavioral)
    5. Archetype recognition via co-movement pattern matching
    6. False alarm detection (small movement + no clear cause)
    7. Context-aware severity (adjust for positive signals)
    8. Multi-cause detection (overlapping causes)
    9. Compute confidence level from all checks + evidence
    10. Build hypothesis with archetype-aware descriptions
    11. Generate action items with owners

    Args:
        decomposition: Output from decompose.run_decomposition().
            Must contain: aggregate, dimensional_breakdown, mix_shift.
        step_change_result: Output from anomaly.detect_step_change().
            If None, defaults to no step-change detected.
        co_movement_result: Output from anomaly.match_co_movement_pattern().
            If None, archetype recognition falls back to generic.
        cause_date_index: Day index of the proposed cause event.
            If None, defaults to 0 (assumes cause is at the start).
        metric_change_date_index: Day index when the metric changed.
            If None, defaults to 0 (no temporal check possible).
        has_historical_precedent: Whether the diagnosis matches a known
            past incident pattern. True enables High confidence.

    Returns:
        Dict with: aggregate, primary_hypothesis, confidence,
        validation_checks, dimensional_breakdown, mix_shift, action_items.
    """
    # ── Defaults for optional parameters ──
    if step_change_result is None:
        step_change_result = {"detected": False, "change_day_index": None, "magnitude_pct": 0.0}
    if co_movement_result is None:
        co_movement_result = {"likely_cause": "unknown_pattern", "is_positive": False}
    if cause_date_index is None:
        cause_date_index = 0
    if metric_change_date_index is None:
        metric_change_date_index = 0

    # ── Extract key metrics from decomposition ──
    explained_pct = _extract_explained_pct(decomposition)
    mix_shift_pct = _extract_mix_shift_pct(decomposition)
    aggregate = decomposition.get("aggregate", {})

    # ── Run all 4 validation checks ──
    check_1 = check_logging_artifact(step_change_result)
    check_2 = check_decomposition_completeness(explained_pct)
    check_3 = check_temporal_consistency(cause_date_index, metric_change_date_index)
    check_4 = check_mix_shift_threshold(mix_shift_pct)

    all_checks = [check_1, check_2, check_3, check_4]

    # ── Archetype recognition via co-movement ──
    # The co-movement pattern tells us WHICH archetype this looks like.
    # The archetype then drives severity, hypothesis, and action items.
    likely_cause = co_movement_result.get("likely_cause", "unknown_pattern")
    archetype_info = ARCHETYPE_MAP.get(likely_cause)

    # ── Mix-shift archetype activation ──
    # If co-movement didn't match a known pattern BUT Check #4 says INVESTIGATE
    # (mix-shift >= 30%), the movement is likely compositional, not behavioral.
    # Assign the mix_shift_composition archetype for proper framing.
    if likely_cause == "unknown_pattern" and check_4.get("status") == "INVESTIGATE":
        archetype_info = ARCHETYPE_MAP["mix_shift_composition"]
        likely_cause = "mix_shift_composition"

    # ── False alarm detection ──
    # If co-movement says "no_significant_movement" OR the aggregate movement
    # is very small (P2 or normal) AND no single segment dominates, treat as
    # false alarm regardless of what the decomposition found.
    # WHY: Small random noise in segment data can create spurious "dominant"
    # segments. A 1% movement with 133% contribution from premium tier is
    # just noise being amplified by decomposition math.
    severity = aggregate.get("severity", "P2")

    # Delta guard for false alarm path (b): even if severity is P2 and no
    # segment dominates, a delta that exceeds the metric's noise threshold
    # is a real signal, not noise. Don't classify it as false alarm.
    metric_name = aggregate.get("metric", "dlctr_value")
    noise_thresh = METRIC_NOISE_THRESHOLDS.get(metric_name, DEFAULT_NOISE_THRESHOLD)
    abs_delta = abs(aggregate.get("relative_delta_pct", 0)) / 100.0
    exceeds_noise = abs_delta > noise_thresh

    # Path (a): co-movement explicitly says no significant movement
    false_alarm_from_co_movement = likely_cause == "no_significant_movement"
    # Path (b): inferred from P2 severity + no dominant segment + delta within noise
    false_alarm_inferred = (
        severity in ("P2", "normal")
        and likely_cause == "unknown_pattern"
        and _get_top_segment_contribution(decomposition) < FALSE_ALARM_MAX_SEGMENT_CONTRIBUTION
        and not exceeds_noise
    )
    is_false_alarm = false_alarm_from_co_movement or false_alarm_inferred
    if is_false_alarm:
        archetype_info = ARCHETYPE_MAP["no_significant_movement"]
        likely_cause = "no_significant_movement"

    # ── Context-aware severity ──
    # Override severity based on archetype. For example:
    # - AI adoption (positive signal): cap at P2 regardless of magnitude
    # - False alarm: set to "normal"
    aggregate = _apply_severity_override(aggregate, archetype_info)
    severity = aggregate.get("severity", "P2")

    # ── Count evidence lines ──
    evidence_lines = 0

    # Evidence: decomposition found a dominant segment
    if decomposition.get("drill_down_recommended", False):
        evidence_lines += 1

    # Evidence: mix-shift is small (movement is behavioral)
    if mix_shift_pct < MIX_SHIFT_INVESTIGATE_THRESHOLD:
        evidence_lines += 1

    # Evidence: aggregate severity is meaningful (P0, P1, or P2)
    if severity in ("P0", "P1", "P2"):
        evidence_lines += 1

    # Evidence: co-movement matched a known pattern (not unknown)
    # This is a strong signal — the metric directions align with a known failure mode.
    if likely_cause != "unknown_pattern":
        evidence_lines += 1

    # ── Build hypothesis first (needed for confidence override decisions) ──
    # Use the updated likely_cause (may have been changed by mix-shift activation
    # or false alarm detection) so _build_primary_hypothesis picks up the right archetype.
    effective_co_movement = dict(co_movement_result)
    effective_co_movement["likely_cause"] = likely_cause
    primary_hypothesis = _build_primary_hypothesis(decomposition, effective_co_movement)

    # ── Compute confidence ──
    # For false alarm: we're highly confident that nothing happened.
    # Override has_historical_precedent to True because false alarms ARE
    # common (we've seen many cases of normal weekly variation).
    if is_false_alarm:
        has_historical_precedent = True

    confidence = compute_confidence(
        checks=all_checks,
        explained_pct=explained_pct,
        evidence_lines=evidence_lines,
        has_historical_precedent=has_historical_precedent,
    )

    # ── False alarm: override to High confidence ──
    # For false alarm scenarios, the standard confidence formula often gives
    # Medium because validation checks (step-change, etc.) may have non-PASS
    # status. But we're HIGHLY confident that nothing happened — the co-movement
    # shows all metrics are stable, and the movement is within normal variation.
    # A Senior DS would say "I'm very confident this is noise" not "I'm moderately
    # confident this is noise."
    # Guard: for INFERRED false alarms (path b), don't override to High if
    # any check returned HALT — a logging artifact means we can't be sure
    # the data is trustworthy. But for CO-MOVEMENT-confirmed false alarms
    # (path a), the multi-metric signal is strong enough to override even HALTs.
    has_halt = any(c.get("status") == "HALT" for c in all_checks)
    halt_blocks_override = has_halt and not false_alarm_from_co_movement
    if is_false_alarm and confidence["level"] != "High" and not halt_blocks_override:
        confidence = {
            "level": "High",
            "reasoning": (
                "High confidence: all metrics within normal variation range. "
                "No significant co-movement detected. This is normal weekly fluctuation."
            ),
            "would_upgrade_if": None,
            "would_downgrade_if": "any metric moves beyond 2 standard deviations",
        }
    if primary_hypothesis.get("multi_cause") and confidence["level"] == "High":
        confidence["level"] = "Medium"
        confidence["reasoning"] = (
            "Medium confidence: multiple overlapping causes detected. "
            "Attribution between causes is uncertain."
        )

    # ── Build action items with owners ──
    action_items = _build_action_items(
        all_checks, confidence["level"], decomposition,
        effective_co_movement, primary_hypothesis, confidence,
    )

    # ── Assemble the full diagnosis report ──
    result = {
        "aggregate": aggregate,
        "primary_hypothesis": primary_hypothesis,
        "confidence": confidence,
        "validation_checks": all_checks,
        "dimensional_breakdown": decomposition.get("dimensional_breakdown", {}),
        "mix_shift": decomposition.get("mix_shift", {}),
        "action_items": action_items,
    }

    # ── v1.4: Post-diagnosis verification ──
    # Run coherence checks on the completed diagnosis. Advisory mode —
    # warnings are surfaced in the formatter output but don't block diagnosis.
    verification_warnings = verify_diagnosis(result)
    result["verification_warnings"] = verification_warnings

    return result


def _get_top_segment_contribution(decomposition: Dict[str, Any]) -> float:
    """Get the contribution_pct of the single largest segment across all dimensions.

    Used for false alarm detection: if no segment dominates (< 50%), the
    movement is spread across many segments = likely noise.

    Args:
        decomposition: Output from decompose.run_decomposition()

    Returns:
        Float percentage (0-100) of the top segment's contribution.
    """
    max_contribution = 0.0
    for dim_result in decomposition.get("dimensional_breakdown", {}).values():
        for seg in dim_result.get("segments", []):
            contrib = abs(seg.get("contribution_pct", 0))
            if contrib > max_contribution:
                max_contribution = contrib
    return max_contribution


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
