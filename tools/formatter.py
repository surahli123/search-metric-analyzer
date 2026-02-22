#!/usr/bin/env python3
"""Formatter tool: generates Slack messages and short reports from diagnosis output.

This is the final stage of the diagnostic pipeline. It takes the structured
diagnosis output (from diagnose.py) and produces two human-readable formats:

1. Slack message (5-15 lines): Quick alert for Eng Leads in a channel.
   Optimized for scanning -- TL;DR first, severity emoji, action items with owners.

2. Short report (1 page): Detailed write-up for async review.
   Contains all sections: summary, decomposition, diagnosis, validation,
   business impact, recommended actions, and confidence change conditions.

DESIGN PRINCIPLES (from Section 9 of the design doc):
- TL;DR always first, always mandatory, max 3 sentences
- Numbers always have context ("78% of drop in Standard tier")
- Confidence stated explicitly with criteria, never hedged language
- Every recommendation has an owner and expected impact
- NO anti-patterns: no hedging, no passive voice, no data dumps

Usage (CLI):
    python tools/formatter.py --input diagnosis.json

Usage (import):
    from tools.formatter import generate_slack_message, generate_short_report
    slack_msg = generate_slack_message(diagnosis_dict)
    report = generate_short_report(diagnosis_dict)

Output: JSON to stdout with "slack_message" and "short_report" keys.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────
# Constants — severity to emoji mapping
# ──────────────────────────────────────────────────

# Severity emojis for Slack messages.
# P0 = critical (red), P1 = warning (yellow), P2 = info (blue).
# These map directly to the severity classifications from diagnose.py.
SEVERITY_EMOJI = {
    "P0": "\U0001f534",  # Red circle
    "P1": "\U0001f7e1",  # Yellow circle
    "P2": "\U0001f535",  # Blue circle
}

# Default emoji when severity is unknown or not provided
DEFAULT_EMOJI = "\u2753"  # Question mark


# ──────────────────────────────────────────────────
# Template Loading
# ──────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Find the project root directory by walking up from this file.

    The project root is identified by the presence of a CLAUDE.md file,
    which all project directories have per our conventions.

    Returns:
        Path to the project root directory.
    """
    current = Path(__file__).resolve().parent
    # Walk up looking for CLAUDE.md (always present at project root)
    for _ in range(5):  # Max 5 levels up to prevent infinite loop
        if (current / "CLAUDE.md").exists():
            return current
        current = current.parent
    # Fallback: assume tools/ is one level below root
    return Path(__file__).resolve().parent.parent


def _load_template(template_name: str) -> str:
    """Load a markdown template from the templates/ directory.

    Templates are stored as markdown files with {placeholder} markers.
    They live in templates/ at the project root.

    Args:
        template_name: Filename of the template (e.g., "slack_message.md").

    Returns:
        Template string content.

    Raises:
        FileNotFoundError: If the template file doesn't exist.
    """
    root = _find_project_root()
    template_path = root / "templates" / template_name
    if not template_path.exists():
        raise FileNotFoundError(
            f"Template not found: {template_path}. "
            f"Expected templates/ directory at project root: {root}"
        )
    return template_path.read_text()


# ──────────────────────────────────────────────────
# Data Extraction Helpers
# ──────────────────────────────────────────────────

def _get_severity(diagnosis: Dict[str, Any]) -> str:
    """Extract severity level from diagnosis output.

    Severity lives in aggregate.severity and tells us how critical
    the metric movement is: P0 (critical), P1 (warning), P2 (info).

    Args:
        diagnosis: Full diagnosis dict from run_diagnosis().

    Returns:
        Severity string (e.g., "P0"). Defaults to "P2" if missing.
    """
    return diagnosis.get("aggregate", {}).get("severity", "P2")


def _get_severity_emoji(severity: str) -> str:
    """Map a severity level to its Slack emoji.

    Args:
        severity: Severity string like "P0", "P1", "P2".

    Returns:
        Emoji character. Falls back to question mark for unknown severities.
    """
    return SEVERITY_EMOJI.get(severity, DEFAULT_EMOJI)


def _get_metric_name(diagnosis: Dict[str, Any]) -> str:
    """Extract the metric name from diagnosis output.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Metric name string (e.g., "dlctr_value"). Defaults to "metric".
    """
    return diagnosis.get("aggregate", {}).get("metric", "metric")


def _get_confidence_level(diagnosis: Dict[str, Any]) -> str:
    """Extract the confidence level from diagnosis output.

    Confidence is computed by diagnose.py based on validation checks,
    explained percentage, evidence lines, and historical precedent.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Confidence level string (e.g., "High", "Medium", "Low").
    """
    return diagnosis.get("confidence", {}).get("level", "Unknown")


def _get_direction(diagnosis: Dict[str, Any]) -> str:
    """Extract the metric movement direction.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Direction string (e.g., "down", "up"). Defaults to "changed".
    """
    return diagnosis.get("aggregate", {}).get("direction", "changed")


def _get_delta_pct(diagnosis: Dict[str, Any]) -> float:
    """Extract the relative delta percentage.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Float percentage (e.g., -6.25). Defaults to 0.0.
    """
    return diagnosis.get("aggregate", {}).get("relative_delta_pct", 0.0)


# ──────────────────────────────────────────────────
# TL;DR Generation
# ──────────────────────────────────────────────────

def _build_tldr(diagnosis: Dict[str, Any]) -> str:
    """Build a 3-sentence TL;DR from diagnosis output.

    The TL;DR follows the formula from the design doc:
    1. What happened (metric + direction + magnitude)
    2. Why (primary hypothesis)
    3. What to do (top action item)

    This is the most important part of both Slack and report output --
    it's what Eng Leads read first (and sometimes ONLY read).

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        TL;DR string, max 3 sentences. No hedging, no passive voice.
    """
    # Sentence 1: What happened
    metric = _get_metric_name(diagnosis)
    direction = _get_direction(diagnosis)
    delta = _get_delta_pct(diagnosis)
    what = f"{metric} moved {direction} {abs(delta):.1f}%"

    # Sentence 2: Why -- from primary hypothesis
    hypothesis = diagnosis.get("primary_hypothesis", {})
    description = hypothesis.get("description", "Root cause under investigation")
    why = description

    # Sentence 3: What to do -- top action item
    action_items = diagnosis.get("action_items", [])
    top_action = _format_single_action(action_items[0]) if action_items else "No action needed"

    return f"{what}. {why}. {top_action}."


# ──────────────────────────────────────────────────
# Action Item Formatting
# ──────────────────────────────────────────────────

def _format_single_action(action_item) -> str:
    """Format a single action item into a readable string.

    Action items can come in two formats:
    1. Dict with "action" and "owner" keys (from test fixtures)
    2. Plain string (from run_diagnosis() output)

    We handle both formats to stay compatible with existing code.

    Args:
        action_item: Either a dict or a string.

    Returns:
        Formatted action string with owner if available.
    """
    if isinstance(action_item, dict):
        action = action_item.get("action", "")
        owner = action_item.get("owner", "")
        if owner:
            return f"{action} ({owner})"
        return action
    # Plain string format from run_diagnosis()
    return str(action_item)


def _format_action_items(diagnosis: Dict[str, Any]) -> str:
    """Format all action items into a bulleted list.

    Each action has an owner -- this is a design doc requirement.
    "Every recommendation has an owner and expected impact."

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Bulleted list string of action items.
    """
    action_items = diagnosis.get("action_items", [])
    if not action_items:
        return "No action required. Continue standard monitoring — re-alert if movement exceeds 2 standard deviations."

    lines = []
    for item in action_items:
        formatted = _format_single_action(item)
        lines.append(f"- {formatted}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────
# Key Findings Builder
# ──────────────────────────────────────────────────

def _build_key_findings(diagnosis: Dict[str, Any]) -> str:
    """Build the key findings section from decomposition and mix-shift data.

    Key findings surface the most actionable numbers with context.
    Design doc rule: "Numbers always have context (% of drop, not just %)."

    We pull findings from:
    1. Dimensional breakdown -- which segments drove the movement
    2. Mix-shift -- how much is compositional vs behavioral
    3. Validation checks -- any notable flags

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Bulleted list of 2-4 key findings with contextual numbers.
    """
    findings = []

    # Finding 1: Top segment contribution from decomposition
    dimensional = diagnosis.get("dimensional_breakdown", {})
    for dim_name, dim_data in dimensional.items():
        segments = dim_data.get("segments", [])
        if segments:
            top = segments[0]
            seg_value = top.get("segment_value", "unknown")
            contrib = top.get("contribution_pct", 0)
            delta = top.get("delta", 0)
            # Derive direction word from delta sign (metric-agnostic)
            direction_word = "decline" if delta < 0 else "increase" if delta > 0 else "change"
            findings.append(
                f"- {contrib:.0f}% of {direction_word} concentrated in {dim_name}={seg_value} "
                f"(delta: {delta:+.3f})"
            )

    # Finding 2: Mix-shift contribution
    mix_shift = diagnosis.get("mix_shift", {})
    mix_pct = mix_shift.get("mix_shift_contribution_pct", 0)
    if mix_pct > 0:
        findings.append(
            f"- Mix-shift accounts for {mix_pct:.0f}% of movement "
            f"(behavioral change dominates)"
        )

    # Finding 3: Overall delta with baseline context
    aggregate = diagnosis.get("aggregate", {})
    baseline = aggregate.get("baseline_mean", 0)
    current = aggregate.get("current_mean", 0)
    delta_pct = aggregate.get("relative_delta_pct", 0)
    if baseline and current:
        findings.append(
            f"- Aggregate moved from {baseline:.3f} to {current:.3f} ({delta_pct:+.1f}%)"
        )

    return "\n".join(findings) if findings else "- No significant findings identified"


# ──────────────────────────────────────────────────
# Confidence Change Conditions
# ──────────────────────────────────────────────────

def _build_confidence_change(diagnosis: Dict[str, Any]) -> str:
    """Build the confidence upgrade/downgrade conditions string.

    The design doc requires: "Always state: 'Would upgrade to {level}
    if {specific condition}.'" This helps the reader understand what
    additional evidence would change the assessment.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        String describing what would change the confidence level.
    """
    confidence = diagnosis.get("confidence", {})
    upgrade = confidence.get("would_upgrade_if")
    downgrade = confidence.get("would_downgrade_if")

    parts = []
    if upgrade:
        parts.append(f"Would upgrade if: {upgrade}")
    if downgrade:
        parts.append(f"Would downgrade if: {downgrade}")

    return "\n".join(parts) if parts else ""


# ──────────────────────────────────────────────────
# Decomposition Table Builder
# ──────────────────────────────────────────────────

def _build_decomposition_table(diagnosis: Dict[str, Any]) -> str:
    """Build a markdown table of dimensional decomposition results.

    Shows each dimension's segments with their contribution percentage
    and delta values. This gives the reader a quick view of WHERE
    the movement happened.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Markdown table string.
    """
    dimensional = diagnosis.get("dimensional_breakdown", {})
    if not dimensional:
        return "No decomposition data available."

    lines = ["| Dimension | Segment | Contribution % | Delta |",
             "|-----------|---------|---------------|-------|"]

    for dim_name, dim_data in dimensional.items():
        segments = dim_data.get("segments", [])
        for seg in segments:
            seg_value = seg.get("segment_value", "unknown")
            contrib = seg.get("contribution_pct", 0)
            delta = seg.get("delta", 0)
            lines.append(
                f"| {dim_name} | {seg_value} | {contrib:.1f}% | {delta:+.4f} |"
            )

    return "\n".join(lines)


# ──────────────────────────────────────────────────
# Validation Table Builder
# ──────────────────────────────────────────────────

def _build_validation_table(diagnosis: Dict[str, Any]) -> str:
    """Build a markdown table of validation check results.

    The 4 mandatory validation checks from diagnose.py:
    1. Logging artifact detection
    2. Decomposition completeness
    3. Temporal consistency
    4. Mix-shift threshold

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Markdown table with check name, status, and detail.
    """
    checks = diagnosis.get("validation_checks", [])
    if not checks:
        return "No validation checks available."

    lines = ["| Check | Status | Detail |",
             "|-------|--------|--------|"]

    for check in checks:
        name = check.get("check", "unknown")
        status = check.get("status", "N/A")
        detail = check.get("detail", "")
        lines.append(f"| {name} | {status} | {detail} |")

    return "\n".join(lines)


# ──────────────────────────────────────────────────
# Business Impact Builder
# ──────────────────────────────────────────────────

def _build_business_impact(diagnosis: Dict[str, Any]) -> str:
    """Generate business impact assessment from severity and delta.

    Maps the severity + delta combination to a human-readable
    impact statement. This helps Eng Leads understand whether
    this needs immediate attention or can wait.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Business impact paragraph.
    """
    severity = _get_severity(diagnosis)
    delta = _get_delta_pct(diagnosis)
    metric = _get_metric_name(diagnosis)
    direction = _get_direction(diagnosis)

    # Build impact statement based on severity
    if severity == "P0":
        urgency = "requires immediate attention"
        impact = (
            f"A {abs(delta):.1f}% {direction} movement in {metric} is a significant "
            f"regression that {urgency}. If sustained, this will impact search quality "
            f"metrics at the aggregate level."
        )
    elif severity == "P1":
        urgency = "should be investigated this week"
        impact = (
            f"A {abs(delta):.1f}% {direction} movement in {metric} {urgency}. "
            f"This is a notable change but not yet at critical threshold."
        )
    else:
        urgency = "is within monitoring range"
        impact = (
            f"A {abs(delta):.1f}% {direction} movement in {metric} {urgency}. "
            f"Continue monitoring but no immediate action required."
        )

    return impact


# ──────────────────────────────────────────────────
# Evidence Bullets Builder
# ──────────────────────────────────────────────────

def _build_evidence_bullets(diagnosis: Dict[str, Any]) -> str:
    """Build evidence bullet points from validation checks and decomposition.

    Collects all PASS checks as supporting evidence for the diagnosis.

    Args:
        diagnosis: Full diagnosis dict.

    Returns:
        Bulleted list of evidence points.
    """
    checks = diagnosis.get("validation_checks", [])
    bullets = []

    for check in checks:
        if check.get("status") == "PASS":
            bullets.append(f"- {check.get('detail', '')}")

    if not bullets:
        return "- No supporting evidence from validation checks"

    return "\n".join(bullets)


# ──────────────────────────────────────────────────
# Main Generators
# ──────────────────────────────────────────────────

def generate_slack_message(diagnosis: Dict[str, Any]) -> str:
    """Generate a Slack message from diagnosis output.

    This is the PRIMARY output for Eng Leads. It must be:
    - 5-15 non-empty lines (scannable in a Slack channel)
    - TL;DR first (what, why, what to do)
    - No hedging, no passive voice, no data dumps
    - Every action has an owner
    - Severity emoji in header

    The message follows the slack_message.md template structure
    but is generated programmatically to enforce the anti-pattern rules.

    Args:
        diagnosis: Full diagnosis dict from run_diagnosis().

    Returns:
        Formatted Slack message string (5-15 non-empty lines).
    """
    severity = _get_severity(diagnosis)
    emoji = _get_severity_emoji(severity)
    metric = _get_metric_name(diagnosis)
    confidence = _get_confidence_level(diagnosis)
    confidence_reasoning = diagnosis.get("confidence", {}).get("reasoning", "")

    # Build each section
    tldr = _build_tldr(diagnosis)
    findings = _build_key_findings(diagnosis)
    actions = _format_action_items(diagnosis)
    conf_change = _build_confidence_change(diagnosis)

    # Assemble the message using the template structure.
    # We build it programmatically rather than using string.format() on the template
    # because we need to control line count and enforce anti-pattern rules.
    lines = [
        f"{emoji} {metric} Movement Alert — [Severity: {severity}] [Confidence: {confidence}]",
        "",
        f"TL;DR: {tldr}",
        "",
        "Key findings:",
        findings,
        "",
        f"Confidence: {confidence} — {confidence_reasoning}",
    ]

    # Add confidence change conditions if they exist
    if conf_change:
        lines.append(conf_change)

    # Add action items
    lines.append("")
    lines.append(actions)

    # v1.4: Surface verification warnings (error-level only for Slack brevity)
    verification_warnings = diagnosis.get("verification_warnings", [])
    error_warnings = [w for w in verification_warnings if w.get("severity") == "error"]
    if error_warnings:
        lines.append("")
        lines.append("Verification notes:")
        for w in error_warnings:
            lines.append(f"- {w['detail']}")

    return "\n".join(lines)


def generate_short_report(diagnosis: Dict[str, Any]) -> str:
    """Generate a short report (1 page) from diagnosis output.

    This is the DETAILED output for async review. It must contain
    all 7 sections from the design doc:
    1. Summary (TL;DR)
    2. Decomposition (segment breakdown table)
    3. Diagnosis (hypothesis + evidence + alternatives)
    4. Validation Checks (4-check status table)
    5. Business Impact (severity interpretation)
    6. Recommended Actions (with owners)
    7. What Would Change This Assessment (upgrade/downgrade conditions)

    Args:
        diagnosis: Full diagnosis dict from run_diagnosis().

    Returns:
        Formatted markdown report string.
    """
    # Extract all the data we need
    metric = _get_metric_name(diagnosis)
    severity = _get_severity(diagnosis)
    confidence = _get_confidence_level(diagnosis)
    delta_pct = _get_delta_pct(diagnosis)
    direction = _get_direction(diagnosis)
    today = date.today().isoformat()

    # Build each section
    tldr = _build_tldr(diagnosis)
    decomp_table = _build_decomposition_table(diagnosis)
    hypothesis = diagnosis.get("primary_hypothesis", {})
    hypothesis_desc = hypothesis.get("description", "No primary hypothesis identified")
    evidence = _build_evidence_bullets(diagnosis)
    validation_table = _build_validation_table(diagnosis)
    business_impact = _build_business_impact(diagnosis)
    actions = _format_action_items(diagnosis)
    conf_change = _build_confidence_change(diagnosis)

    # Determine period description from direction
    period = f"({direction} movement)"

    # Alternatives considered -- derive from hypothesis category
    category = hypothesis.get("category", "unknown")
    alternatives = _build_alternatives(category)

    # Assemble the report using the template structure
    report = f"""# Metric Movement Report: {metric} {delta_pct:+.1f}% {period}
**Date:** {today} | **Severity:** {severity} | **Confidence:** {confidence}

## Summary
{tldr}

## Decomposition
{decomp_table}

## Diagnosis
**Primary hypothesis:** {hypothesis_desc}
**Evidence:**
{evidence}
**Alternatives considered:** {alternatives}

## Validation Checks
{validation_table}

## Business Impact
{business_impact}

## Recommended Actions
{actions}

## What Would Change This Assessment
{conf_change}"""

    # v1.4: Append verification notes if any warnings exist
    verification_warnings = diagnosis.get("verification_warnings", [])
    if verification_warnings:
        warning_lines = []
        for w in verification_warnings:
            level = w.get("severity", "warning").upper()
            warning_lines.append(f"- [{level}] {w['detail']}")
        report += f"\n\n## Verification Notes\n" + "\n".join(warning_lines)

    return report


def _build_alternatives(primary_category: str) -> str:
    """Build a list of alternative hypotheses considered.

    Given the primary hypothesis category, list the other standard
    categories that were implicitly ruled out. This shows the reader
    that we considered multiple explanations.

    The standard hypothesis categories from the diagnostic workflow:
    - algorithm_model: Ranking model or algorithm change
    - data_pipeline: Logging, instrumentation, or data quality issue
    - mix_shift: Traffic composition change
    - external: Seasonality, user behavior shift

    Args:
        primary_category: The primary hypothesis category string.

    Returns:
        String listing alternative categories considered.
    """
    # 9 hypothesis categories from metric_definitions.yaml hypothesis_priority.
    # Must match the design doc's fixed investigation ordering exactly.
    all_categories = {
        "instrumentation": "Instrumentation/Logging anomaly",
        "connector": "Connector/data pipeline change",
        # Source: Rovo — L0 Query Intelligence layer (intent classification,
        # spell correction, query reformulation). Check early — upstream of ranking.
        "query_understanding": "Query understanding regression (intent, reformulation, spelling)",
        "algorithm_model": "Algorithm/Model change (ranking, embedding)",
        "experiment": "Experiment ramp/de-ramp",
        "ai_feature_effect": "AI feature effect (adoption, threshold, model)",
        "seasonal": "Seasonal/External pattern",
        "user_behavior": "User behavior shift",
        "mix_shift": "Traffic composition change (mix-shift)",
    }

    alternatives = []
    for cat, desc in all_categories.items():
        if cat != primary_category:
            alternatives.append(f"{desc} (considered, not primary)")

    if not alternatives:
        return "Standard diagnostic categories reviewed"

    return "; ".join(alternatives)


# ──────────────────────────────────────────────────
# Combined Output
# ──────────────────────────────────────────────────

def format_diagnosis_output(diagnosis: Dict[str, Any]) -> Dict[str, str]:
    """Generate both Slack message and short report from diagnosis output.

    This is the convenience function that produces both output formats
    in a single call. Useful when you need both (e.g., for the eval framework).

    Args:
        diagnosis: Full diagnosis dict from run_diagnosis().

    Returns:
        Dict with "slack_message" and "short_report" keys, both strings.
    """
    return {
        "slack_message": generate_slack_message(diagnosis),
        "short_report": generate_short_report(diagnosis),
    }


# ──────────────────────────────────────────────────
# CLI interface -- for Claude Code to call via Bash tool
# ──────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for CLI usage."""
    parser = argparse.ArgumentParser(
        description="Generate Slack message and short report from diagnosis output"
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to JSON file with diagnosis output (from diagnose.py)"
    )
    return parser.parse_args()


def main():
    """CLI entry point: load diagnosis JSON, generate formatted output, print to stdout."""
    args = parse_args()

    # Load the diagnosis output JSON
    input_path = Path(args.input)
    if not input_path.exists():
        print(json.dumps({"error": f"File not found: {args.input}"}))
        sys.exit(1)

    with open(input_path) as f:
        diagnosis = json.load(f)

    # Generate both output formats
    result = format_diagnosis_output(diagnosis)

    # Output JSON to stdout for Claude Code to read
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
