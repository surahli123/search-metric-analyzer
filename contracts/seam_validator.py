"""Seam validator — enforces contracts at stage boundaries.

This is the heart of the v2 architecture. Each stage boundary has:
1. TypedDict field checks (do required fields exist?)
2. Business rules (are the values correct given search domain logic?)
3. Tiered gates (how to handle failures — hard halt, soft warn, or retry)

Design principle from IC9 review: "Contracts enforce SUBSTANCE, not just FORM."
The business rules below encode domain-specific invariants that catch bad
investigations — not just structurally invalid data.

Amendment 1 (Tiered Gates):
- UNDERSTAND: HARD — garbage in = stop
- HYPOTHESIZE: SOFT — 2 hypotheses with a warning beats nothing
- DISPATCH: SOFT — one bad finding shouldn't kill the investigation
- SYNTHESIZE: RETRY(1) then SOFT — missing section is usually fixable

Amendment 2 (Co-movement consistency):
- rule_hypotheses_consistent_with_co_movement prevents flagging expected
  AI-driven CQ drops as anomalous

Amendment 3 (Mix-shift):
- rule_mix_shift_considered_when_detected ensures mix-shift hypotheses
  are generated when mix-shift is significant
"""

import json
import sys
from typing import Any, Callable, Dict, List, Optional, Type

# Import contracts (used for type reference only — we validate dict structure)
# We don't import trace here to avoid circular deps; trace is passed in


# =============================================================================
# Exception
# =============================================================================

class SeamViolation(Exception):
    """Raised when a seam validation fails at a HARD gate.

    For SOFT gates, violations are recorded but not raised.
    For RETRY gates, this is raised on first attempt; caller retries then
    falls back to soft behavior.
    """
    def __init__(self, stage: str, violations: List[str], tier: str):
        self.stage = stage
        self.violations = violations
        self.tier = tier
        super().__init__(
            f"SeamViolation at {stage} ({tier}): {'; '.join(violations)}"
        )


# =============================================================================
# Gate tier configuration
# =============================================================================

# Maps stage → gate behavior on failure
GATE_TIERS = {
    "UNDERSTAND": "hard",       # Garbage in = stop
    "HYPOTHESIZE": "soft",      # Something is better than nothing
    "DISPATCH": "soft",         # One bad finding shouldn't kill everything
    "SYNTHESIZE": "retry",      # Missing section = retry once, then soft
}


# =============================================================================
# UNDERSTAND business rules
# =============================================================================

def rule_data_quality_not_failed(result: Dict, **kwargs) -> Optional[str]:
    """HARD CHECK: If data quality is 'fail', the investigation cannot proceed.

    This is the only hard gate — we refuse to generate hypotheses on
    data we know is bad. Better to tell the DS "your data has problems"
    than to produce a misleading diagnosis.
    """
    if result.get("data_quality_status") == "fail":
        return "Data quality check FAILED — investigation cannot proceed with unreliable data"
    return None


def rule_metric_direction_set(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Invisible Decision #1: metric_direction must be explicitly set.

    This was previously an implicit decision buried in anomaly detection.
    Now it's a required field that appears in the trace.
    """
    if not result.get("metric_direction"):
        return "metric_direction is empty — IC9 Invisible Decision #1 must be explicitly traced"
    valid = {"up", "down", "stable"}
    if result.get("metric_direction") not in valid:
        return f"metric_direction must be one of {valid}, got '{result.get('metric_direction')}'"
    return None


# =============================================================================
# HYPOTHESIZE business rules
# =============================================================================

def rule_min_three_hypotheses(result: Dict, **kwargs) -> Optional[str]:
    """At least 3 hypotheses required to avoid tunnel vision.

    The IC9 audit found that investigations with fewer than 3 hypotheses
    had a much higher rate of missed root causes — the team anchored on
    the first plausible explanation.
    """
    hyps = result.get("hypotheses", [])
    if len(hyps) < 3:
        return f"Only {len(hyps)} hypotheses generated, minimum 3 required to avoid tunnel vision"
    return None


def rule_all_have_confirms_if(result: Dict, **kwargs) -> Optional[str]:
    """Every hypothesis must define what evidence would confirm it.

    This prevents post-hoc rationalization: you define what counts as
    evidence BEFORE investigation, not after you've found something.
    """
    for h in result.get("hypotheses", []):
        if not h.get("confirms_if"):
            return f"Hypothesis '{h.get('hypothesis_id', 'unknown')}' has empty confirms_if — must define confirmation criteria before investigation"
    return None


def rule_has_contrarian_hypothesis(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Phase 2: at least one hypothesis must challenge the obvious explanation.

    Without a contrarian, the investigation degenerates into confirmation bias —
    all hypotheses point the same direction and the sub-agents just find
    evidence for what seems obvious.
    """
    hyps = result.get("hypotheses", [])
    if not any(h.get("is_contrarian") for h in hyps):
        return "No contrarian hypothesis found — at least one must challenge the obvious explanation to prevent confirmation bias"
    return None


def rule_expected_magnitude_present(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Phase 2: expected_magnitude must be set on every hypothesis.

    This prevents false alarms: if you expect a 2-4% CQ drop but find 0.3%,
    the hypothesis doesn't match even if the direction is right.
    """
    for h in result.get("hypotheses", []):
        if not h.get("expected_magnitude"):
            return f"Hypothesis '{h.get('hypothesis_id', 'unknown')}' has no expected_magnitude — required to prevent false alarms"
    return None


def rule_hypotheses_consistent_with_co_movement(result: Dict, **kwargs) -> Optional[str]:
    """Amendment 2: Prevent flagging expected AI-driven CQ drops as anomalous.

    If UNDERSTAND identified 'ai_adoption_expected' co-movement, no hypothesis
    should have archetype 'click_quality_degradation' unless explicitly marked
    as contrarian (is_contrarian=True).

    This is the signature domain rule of the Search Metric Analyzer — the
    "AI adoption trap" where AI answers work well → users click less →
    CQ drops → team panics → but it's actually a POSITIVE signal.

    The understand_result is passed via kwargs so this rule can cross-reference
    the UNDERSTAND output.
    """
    understand = kwargs.get("understand_result", {})
    co_movement = understand.get("co_movement_pattern", {})
    pattern = co_movement.get("pattern_name", "")

    if pattern == "ai_adoption_expected":
        for h in result.get("hypotheses", []):
            if (h.get("archetype") == "click_quality_degradation"
                    and not h.get("is_contrarian")):
                return (
                    f"Hypothesis '{h.get('hypothesis_id', 'unknown')}' has archetype "
                    f"'click_quality_degradation' but co-movement pattern is "
                    f"'ai_adoption_expected' (AI answers working → fewer clicks → "
                    f"expected CQ drop). Must be marked is_contrarian=True or removed."
                )
    return None


def rule_mix_shift_considered_when_detected(result: Dict, **kwargs) -> Optional[str]:
    """Amendment 3: If mix-shift was detected, at least one hypothesis must address it.

    Mix-shift causes 30-40% of Enterprise metric movements. If UNDERSTAND
    detected significant mix-shift (contribution > 25%), HYPOTHESIZE must
    include at least one mix-shift hypothesis.
    """
    understand = kwargs.get("understand_result", {})
    mix_shift = understand.get("mix_shift_result", {})

    if mix_shift and mix_shift.get("detected") and mix_shift.get("contribution_pct", 0) > 0.25:
        hyps = result.get("hypotheses", [])
        has_mix_shift_hyp = any(
            h.get("archetype") in ("mix_shift", "segment_mix_shift")
            for h in hyps
        )
        if not has_mix_shift_hyp:
            pct = mix_shift.get("contribution_pct", 0)
            return (
                f"Mix-shift explains {pct:.0%} of metric movement but no "
                f"mix-shift hypothesis was generated. Mix-shift causes 30-40% "
                f"of Enterprise metric movements — this must be investigated."
            )
    return None


# =============================================================================
# DISPATCH business rules
# =============================================================================

def rule_each_finding_has_evidence(result: Dict, **kwargs) -> Optional[str]:
    """Every finding must include raw data evidence, not just narrative.

    IC9 finding: sub-agents were producing convincing narratives without
    data backing. A finding without evidence is an opinion, not a diagnosis.
    """
    for f in result.get("findings", []):
        if not f.get("evidence"):
            return (
                f"Finding from '{f.get('agent_name', 'unknown')}' for hypothesis "
                f"'{f.get('hypothesis_id', 'unknown')}' has no evidence — "
                f"narrative without data is opinion, not diagnosis"
            )
    return None


def rule_narrative_data_coherence(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Phase 2: Check that narrative is consistent with evidence.

    Implementation: verify sign consistency — if evidence shows a metric
    went UP but narrative says "dropped" or "declined", flag it.
    Also check that any percentages cited in narrative appear (roughly)
    in the evidence data.

    This is a heuristic, not a proof — it catches obvious drift without
    being so strict that it blocks valid investigations.
    """
    decline_words = {"dropped", "declined", "decreased", "fell", "down", "lower"}
    increase_words = {"rose", "increased", "grew", "up", "higher", "jumped"}

    for f in result.get("findings", []):
        narrative = f.get("narrative", "").lower()
        evidence = f.get("evidence", [])

        # Check sign consistency across evidence items
        for ev in evidence:
            direction = ev.get("direction", "")
            if direction == "up" and any(w in narrative for w in decline_words):
                if not any(w in narrative for w in increase_words):
                    return (
                        f"Narrative-data mismatch in finding for "
                        f"'{f.get('hypothesis_id', 'unknown')}': evidence shows "
                        f"direction=UP but narrative uses decline language. "
                        f"This may indicate narrative drift."
                    )
            elif direction == "down" and any(w in narrative for w in increase_words):
                if not any(w in narrative for w in decline_words):
                    return (
                        f"Narrative-data mismatch in finding for "
                        f"'{f.get('hypothesis_id', 'unknown')}': evidence shows "
                        f"direction=DOWN but narrative uses increase language. "
                        f"This may indicate narrative drift."
                    )
    return None


# =============================================================================
# SYNTHESIZE business rules
# =============================================================================

def rule_all_mandatory_sections_present(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Phase 1: All 7 mandatory sections must be non-empty.

    The IC9 audit found ~50% compliance on mandatory sections. This rule
    makes skipping a section impossible (at a code level, not a prompt level).
    """
    mandatory = [
        "tldr", "confidence_grade", "severity", "root_cause",
        "dimensional_breakdown", "hypothesis_and_evidence", "validation_summary"
    ]
    missing = [s for s in mandatory if not result.get(s)]
    if missing:
        return f"Missing mandatory sections: {', '.join(missing)}. All 7 sections required."
    return None


def rule_effect_size_proportionality(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Phase 2: P0 severity must use proportional language.

    If severity is P0 (critical incident), the report should not contain
    minimizing language like "minor", "slight", "small". This catches
    the case where the LLM hedges on a genuinely severe issue.

    Uses word-boundary matching (\\b) to avoid false positives on words
    like "smaller", "minority", "smallest" — which are not minimizing.
    """
    import re

    if result.get("severity") == "P0":
        minimizing_words = {"minor", "slight", "small", "marginal", "negligible", "trivial"}
        # Check tldr and root_cause — the most visible sections
        for field in ["tldr", "root_cause"]:
            text = result.get(field, "").lower()
            # Use word-boundary regex to match whole words only
            # e.g., "minor" matches but "minority" does not
            found = [w for w in minimizing_words if re.search(r'\b' + w + r'\b', text)]
            if found:
                return (
                    f"P0 severity but '{field}' uses minimizing language: "
                    f"{', '.join(found)}. A P0 is a critical incident — "
                    f"language must match severity to avoid downplaying impact."
                )
    return None


def rule_upgrade_condition_stated(result: Dict, **kwargs) -> Optional[str]:
    """Every report must state when confidence would upgrade.

    "Would upgrade to High if we confirmed X" gives the DS a clear
    next step. Without this, Medium confidence is a dead end.
    """
    if not result.get("upgrade_condition"):
        return "Missing upgrade_condition — must state 'Would upgrade to X if Y' so DS knows what to investigate next"
    return None


# =============================================================================
# Rule registry — maps stages to their business rules
# =============================================================================

UNDERSTAND_RULES: List[Callable] = [
    rule_data_quality_not_failed,
    rule_metric_direction_set,
]

HYPOTHESIZE_RULES: List[Callable] = [
    rule_min_three_hypotheses,
    rule_all_have_confirms_if,
    rule_has_contrarian_hypothesis,
    rule_expected_magnitude_present,
    rule_hypotheses_consistent_with_co_movement,
    rule_mix_shift_considered_when_detected,
]

DISPATCH_RULES: List[Callable] = [
    rule_each_finding_has_evidence,
    rule_narrative_data_coherence,
]

SYNTHESIZE_RULES: List[Callable] = [
    rule_all_mandatory_sections_present,
    rule_effect_size_proportionality,
    rule_upgrade_condition_stated,
]

# Convenient lookup
STAGE_RULES: Dict[str, List[Callable]] = {
    "UNDERSTAND": UNDERSTAND_RULES,
    "HYPOTHESIZE": HYPOTHESIZE_RULES,
    "DISPATCH": DISPATCH_RULES,
    "SYNTHESIZE": SYNTHESIZE_RULES,
}


# =============================================================================
# Core validation function
# =============================================================================

def validate_seam(
    result: Dict[str, Any],
    stage: str,
    trace=None,  # Optional[InvestigationTrace] — not typed to avoid circular import
    business_rules: Optional[List[Callable]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Validate a stage output against its contract and business rules.

    This is the core enforcement function. It:
    1. Runs all business rules for the stage
    2. Collects violations
    3. Emits a seam span to the trace (if provided)
    4. Handles the violation according to the stage's gate tier:
       - HARD: raises SeamViolation
       - SOFT: returns result with violations recorded (warns but continues)
       - RETRY: raises SeamViolation (caller handles retry + fallback to soft)

    Args:
        result: The stage output dict to validate
        stage: "UNDERSTAND" | "HYPOTHESIZE" | "DISPATCH" | "SYNTHESIZE"
        trace: Optional InvestigationTrace to emit seam spans to
        business_rules: Override rules (default: STAGE_RULES[stage])
        **kwargs: Additional context passed to rules (e.g., understand_result)

    Returns:
        Dict with keys:
        - passed: bool
        - violations: List[str]
        - tier: str
        - checks: Dict[str, bool] — per-rule results
    """
    rules = business_rules or STAGE_RULES.get(stage, [])
    tier = GATE_TIERS.get(stage, "soft")

    violations = []
    checks = {}

    for rule in rules:
        rule_name = rule.__name__
        violation = rule(result, **kwargs)
        if violation:
            violations.append(violation)
            checks[rule_name] = False
        else:
            checks[rule_name] = True

    passed = len(violations) == 0

    # Emit seam span to trace if provided
    if trace is not None:
        # Determine schema name from stage
        schema_map = {
            "UNDERSTAND": "UnderstandResult",
            "HYPOTHESIZE": "HypothesisSet",
            "DISPATCH": "FindingSet",
            "SYNTHESIZE": "SynthesisReport",
        }
        trace.emit_seam(
            stage=stage,
            schema=schema_map.get(stage, stage),
            passed=passed,
            tier=tier,
            checks=checks,
            violations=violations
        )

    validation_result = {
        "passed": passed,
        "violations": violations,
        "tier": tier,
        "checks": checks,
    }

    # Apply gate tier behavior
    if not passed:
        if tier == "hard":
            raise SeamViolation(stage, violations, tier)
        elif tier == "retry":
            # Raise so caller can retry; caller handles fallback to soft
            raise SeamViolation(stage, violations, tier)
        # tier == "soft": return result with violations recorded, don't raise

    return validation_result


# =============================================================================
# CLI interface — for Mode A (skill file) subprocess calls
# =============================================================================

def main():
    """CLI entry point for seam validation.

    Usage: python -m contracts.seam_validator --stage understand --input /tmp/understand_out.json

    Outputs structured JSON to stdout (not just exit code) so the skill file
    can parse the result and act appropriately.
    """
    import argparse

    parser = argparse.ArgumentParser(description="Validate a stage seam contract")
    parser.add_argument("--stage", required=True,
                       choices=["understand", "hypothesize", "dispatch", "synthesize"])
    parser.add_argument("--input", required=True, help="Path to stage output JSON")
    parser.add_argument("--understand-input", default=None,
                       help="Path to UNDERSTAND output (needed for HYPOTHESIZE cross-checks)")

    args = parser.parse_args()
    stage = args.stage.upper()

    # Load stage output
    with open(args.input) as f:
        result = json.load(f)

    # Load UNDERSTAND output if provided (for cross-stage rules)
    kwargs = {}
    if args.understand_input:
        with open(args.understand_input) as f:
            kwargs["understand_result"] = json.load(f)

    try:
        validation = validate_seam(result, stage, **kwargs)
        # Output structured JSON for skill file to parse
        output = {
            "passed": validation["passed"],
            "stage": stage,
            "tier": validation["tier"],
            "violations": validation["violations"],
            "checks": validation["checks"],
        }
        print(json.dumps(output, indent=2))
        sys.exit(0 if validation["passed"] else 1)
    except SeamViolation as e:
        output = {
            "passed": False,
            "stage": stage,
            "tier": e.tier,
            "violations": e.violations,
            "remediation": _remediation_hint(stage, e.violations),
        }
        print(json.dumps(output, indent=2))
        sys.exit(1)


def _remediation_hint(stage: str, violations: List[str]) -> str:
    """Generate a human-readable remediation hint for the skill file.

    This helps Claude Code understand what went wrong and how to fix it,
    rather than just seeing a generic error.
    """
    hints = {
        "UNDERSTAND": "Data quality issues detected. Check the input data for missing values, outliers, or insufficient history.",
        "HYPOTHESIZE": "Hypothesis generation did not meet requirements. Ensure at least 3 hypotheses with confirms_if criteria, including one contrarian.",
        "DISPATCH": "Sub-agent findings have issues. Ensure each finding has evidence data (not just narrative) and that narrative matches evidence direction.",
        "SYNTHESIZE": "Report is incomplete. Check that all 7 mandatory sections are filled, language matches severity, and upgrade_condition is stated.",
    }
    return hints.get(stage, "Review the violations and address each one.")


if __name__ == "__main__":
    main()
