"""Seam validator — enforces contracts at stage boundaries.

This is the heart of the v2 architecture. Each stage boundary has:
1. TypedDict field checks (do required fields exist?)
2. Business rules (are the values correct given search domain logic?)
3. Tiered gates (how to handle failures — hard halt, soft warn, or retry)

Design principle from IC9 review: "Contracts enforce SUBSTANCE, not just FORM."
The business rules below encode domain-specific invariants that catch bad
investigations — not just structurally invalid data.

Amendment 1 (Tiered Gates):
- QUESTION_PARSE: HARD — bad brief = wrong mode = wasted work (Wave 5)
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

Wave 5 additions (4 new rules, 13→17 total + QUESTION_PARSE stage):
- rule_question_brief_valid: validates QuestionBrief from question parser
- rule_srm_check: experiment arm ratio validation
- rule_mode_compliance_simple: Simple mode can't have DISPATCH findings
- rule_report_quality_score: 12-point report quality rubric
"""

import json
import re
import sys
from typing import Any, Callable, Dict, List, Optional, Type

# Domain-specific rules imported from their canonical home in the domain module.
# WHY this cross-layer import exists: STAGE_RULES needs to contain ALL rules
# (generic + domain-specific) for backward compatibility — existing code calls
# validate_seam() without a domain parameter and expects all 17 rules to run.
# When the data_analysis domain is added, it will bypass STAGE_RULES and provide
# its own rules via domain.get_quality_rules(). At that point, the domain-specific
# rules can be removed from STAGE_RULES and this import can be deleted.
from domains.search_metrics.rules import (
    rule_question_brief_valid,
    rule_hypotheses_consistent_with_co_movement,
    rule_mix_shift_considered_when_detected,
    rule_effect_size_proportionality,
    VALID_QUESTION_TYPES,  # Re-export for any code that imports from here
)

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
    "QUESTION_PARSE": "hard",   # Bad question brief = wrong mode = wasted work
    "UNDERSTAND": "hard",       # Garbage in = stop
    "HYPOTHESIZE": "soft",      # Something is better than nothing
    "DISPATCH": "soft",         # One bad finding shouldn't kill everything
    "SYNTHESIZE": "retry",      # Missing section = retry once, then soft
}


# =============================================================================
# QUESTION_PARSE business rules
# =============================================================================
# rule_question_brief_valid + VALID_QUESTION_TYPES are imported from
# domains.search_metrics.rules (search-specific question types).


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
        return ("Data quality check FAILED — investigation cannot proceed with unreliable data. "
                "Recheck the data source: verify completeness > 95% and freshness < 60 minutes before retrying.")
    return None


def rule_metric_direction_set(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Invisible Decision #1: metric_direction must be explicitly set.

    This was previously an implicit decision buried in anomaly detection.
    Now it's a required field that appears in the trace.
    """
    if not result.get("metric_direction"):
        return ("metric_direction is empty — IC9 Invisible Decision #1 must be explicitly traced. "
                "Set metric_direction to one of {up, down, stable} based on the aggregate delta.")
    valid = {"up", "down", "stable"}
    if result.get("metric_direction") not in valid:
        return (f"metric_direction must be one of {valid}, got '{result.get('metric_direction')}'. "
                f"Set to one of the valid values based on the aggregate delta direction.")
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
        return (f"Only {len(hyps)} hypotheses generated, minimum 3 required to avoid tunnel vision. "
                f"Add at least one contrarian hypothesis that challenges the primary pattern.")
    return None


def rule_all_have_confirms_if(result: Dict, **kwargs) -> Optional[str]:
    """Every hypothesis must define what evidence would confirm it.

    This prevents post-hoc rationalization: you define what counts as
    evidence BEFORE investigation, not after you've found something.
    """
    for h in result.get("hypotheses", []):
        if not h.get("confirms_if"):
            return (f"Hypothesis '{h.get('hypothesis_id', 'unknown')}' has empty confirms_if — must define confirmation criteria before investigation. "
                    f"Define specific, testable confirmation criteria (e.g., 'ranking logs show model change in date range').")
    return None


def rule_has_contrarian_hypothesis(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Phase 2: at least one hypothesis must challenge the obvious explanation.

    Without a contrarian, the investigation degenerates into confirmation bias —
    all hypotheses point the same direction and the sub-agents just find
    evidence for what seems obvious.
    """
    hyps = result.get("hypotheses", [])
    if not any(h.get("is_contrarian") for h in hyps):
        return ("No contrarian hypothesis found — at least one must challenge the obvious explanation to prevent confirmation bias. "
                "Add a hypothesis with is_contrarian=True that proposes an alternative explanation for the metric movement.")
    return None


def rule_expected_magnitude_present(result: Dict, **kwargs) -> Optional[str]:
    """IC9 Phase 2: expected_magnitude must be set on every hypothesis.

    This prevents false alarms: if you expect a 2-4% CQ drop but find 0.3%,
    the hypothesis doesn't match even if the direction is right.
    """
    for h in result.get("hypotheses", []):
        if not h.get("expected_magnitude"):
            return (f"Hypothesis '{h.get('hypothesis_id', 'unknown')}' has no expected_magnitude — required to prevent false alarms. "
                    f"Add expected_magnitude as a range (e.g., '2-4% drop') based on the archetype's historical impact.")
    return None


# rule_hypotheses_consistent_with_co_movement and rule_mix_shift_considered_when_detected
# are imported from domains.search_metrics.rules (search-specific domain invariants).


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
                f"narrative without data is opinion, not diagnosis. "
                f"Include at least one evidence item with data values (e.g., {{metric: value, delta: -X%}})."
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
                        f"This may indicate narrative drift. "
                        f"Revise the narrative to match evidence direction, or add qualifying language explaining the discrepancy."
                    )
            elif direction == "down" and any(w in narrative for w in increase_words):
                if not any(w in narrative for w in decline_words):
                    return (
                        f"Narrative-data mismatch in finding for "
                        f"'{f.get('hypothesis_id', 'unknown')}': evidence shows "
                        f"direction=DOWN but narrative uses increase language. "
                        f"This may indicate narrative drift. "
                        f"Revise the narrative to match evidence direction, or add qualifying language explaining the discrepancy."
                    )
    return None


def rule_srm_check(result: Dict, **kwargs) -> Optional[str]:
    """Wave 5 SOFT CHECK: Experiment investigations must validate arm ratio balance.

    SRM (Sample Ratio Mismatch) is when experiment arm sizes deviate from
    the expected ratio. A 50/50 experiment with 55/45 actual split means
    the randomization failed — any conclusions are unreliable.

    This only fires for experiment-type investigations (passed via kwargs).
    The 1% tolerance matches industry standard (Google, LinkedIn, Airbnb
    all use similar thresholds for SRM detection).
    """
    question_type = kwargs.get("question_type")
    if question_type != "experiment":
        return None  # Only applies to experiment investigations

    # Look for SRM data in the findings
    for finding in result.get("findings", []):
        srm_data = finding.get("srm_check")
        if srm_data:
            expected_ratio = srm_data.get("expected_ratio", 0.5)
            actual_ratio = srm_data.get("actual_ratio")
            if actual_ratio is not None:
                deviation = abs(actual_ratio - expected_ratio)
                # 1% tolerance — standard threshold for SRM detection
                # Use > 0.01 + epsilon to handle floating point imprecision
                if deviation > 0.0100001:
                    return (
                        f"SRM detected: expected arm ratio {expected_ratio:.2%}, "
                        f"actual {actual_ratio:.2%} (deviation {deviation:.2%} > 1% threshold). "
                        f"Experiment randomization may have failed — results are unreliable. "
                        f"Investigate randomization logic before drawing conclusions."
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
        return (f"Missing mandatory sections: {', '.join(missing)}. All 7 sections required. "
                f"Populate each missing section with at least one substantive sentence — do not leave any blank.")
    return None


# rule_effect_size_proportionality is imported from domains.search_metrics.rules
# (P0 severity language check — depends on search metric alert threshold system).


def rule_upgrade_condition_stated(result: Dict, **kwargs) -> Optional[str]:
    """Every report must state when confidence would upgrade.

    "Would upgrade to High if we confirmed X" gives the DS a clear
    next step. Without this, Medium confidence is a dead end.
    """
    if not result.get("upgrade_condition"):
        return "Missing upgrade_condition — must state 'Would upgrade to X if Y' so DS knows what to investigate next"
    return None


def rule_mode_compliance_simple(result: Dict, **kwargs) -> Optional[str]:
    """Wave 5 SOFT CHECK: Simple-mode reports must not contain DISPATCH findings.

    Simple mode is for direct knowledge lookups ("what's the CQ formula?").
    If a simple-mode report contains investigation findings, it means the
    question was misclassified — it should have been Medium or Complex.

    This catches mode selection errors early, before the user sees a
    report that's either over-engineered (Simple question got full pipeline)
    or under-investigated (Complex question got Simple treatment).
    """
    mode = kwargs.get("mode")
    if mode != "simple":
        return None  # Only applies to simple mode

    # Simple mode should NOT have findings from DISPATCH
    findings = result.get("dispatch_findings", [])
    if findings:
        return (
            f"Simple-mode report contains {len(findings)} DISPATCH findings — "
            f"simple questions should be answered from knowledge alone, "
            f"not through hypothesis investigation. Either the question was "
            f"misclassified (should be Medium/Complex) or the pipeline "
            f"over-investigated. Review mode selection logic."
        )
    return None


# Quality score rubric weights — each criterion is worth 0-3 points
# Total possible: 12 (4 criteria × 3 points each)
REPORT_QUALITY_CRITERIA = {
    "tldr_length": 3,          # TL;DR between 1-5 sentences
    "evidence_cited": 3,       # At least one evidence reference
    "no_hedge_words": 3,       # No weasel words in conclusions
    "actionable_next_steps": 3, # At least one recommended action
}
REPORT_QUALITY_THRESHOLD = 6  # Minimum passing score (50%)

# Hedge words that weaken conclusions — these indicate the LLM is hedging
# instead of stating findings directly. Common LLM failure mode.
HEDGE_WORDS = {
    "it appears", "might suggest", "potentially", "it seems",
    "could possibly", "may indicate", "it is possible",
}


def rule_report_quality_score(result: Dict, **kwargs) -> Optional[str]:
    """Wave 5 SOFT CHECK: Reports must meet a minimum quality score (0-12 scale).

    Scoring rubric (each criterion 0-3 points):
    1. tldr_length: TL;DR exists and is 1-5 sentences (not empty, not a wall of text)
    2. evidence_cited: Report references specific data values or evidence
    3. no_hedge_words: Conclusions don't use weasel words (appears, might, possibly)
    4. actionable_next_steps: At least one recommended action exists

    Threshold: 6/12 (50%). This is deliberately lenient because:
    - We're adding this gate to catch obviously bad reports, not perfect ones
    - The SYNTHESIZE retry mechanism already handles most quality issues
    - A too-strict threshold would cause excessive retries

    Why these 4 criteria? They're the cheapest to check mechanically and
    catch the most common LLM failure modes: empty reports, evidence-free
    conclusions, hedge-word soup, and missing action items.
    """
    score = 0
    issues = []

    # --- Criterion 1: TL;DR length (0-3) ---
    tldr = result.get("tldr", "")
    if tldr:
        # Count sentences (rough heuristic: split on period + space)
        sentences = [s.strip() for s in tldr.split(". ") if s.strip()]
        if 1 <= len(sentences) <= 5:
            score += 3  # Perfect: concise summary
        elif len(sentences) > 5:
            score += 1  # Too verbose — penalize but don't zero out
            issues.append("tldr too long (>5 sentences)")
        else:
            score += 2  # Edge case: one long sentence
    else:
        issues.append("tldr is empty")

    # --- Criterion 2: Evidence cited (0-3) ---
    # Check if the report references specific data (numbers, percentages)
    evidence_fields = ["root_cause", "hypothesis_and_evidence", "dimensional_breakdown"]
    has_evidence = False
    for field in evidence_fields:
        text = result.get(field, "")
        # Look for numeric patterns that indicate real data (e.g., "3.2%", "-2.1pp")
        if re.search(r'\d+\.?\d*[%p]', text):
            has_evidence = True
            break
    if has_evidence:
        score += 3
    else:
        issues.append("no numeric evidence cited in report body")

    # --- Criterion 3: No hedge words in conclusions (0-3) ---
    # Check tldr and root_cause — the most authoritative sections
    conclusion_text = f"{result.get('tldr', '')} {result.get('root_cause', '')}".lower()
    found_hedges = [hw for hw in HEDGE_WORDS if hw in conclusion_text]
    if not found_hedges:
        score += 3
    elif len(found_hedges) <= 1:
        score += 1  # One hedge word — minor deduction
        issues.append(f"hedge word found: '{found_hedges[0]}'")
    else:
        issues.append(f"multiple hedge words: {', '.join(found_hedges[:3])}")

    # --- Criterion 4: Actionable next steps (0-3) ---
    actions = result.get("recommended_actions", [])
    if actions and len(actions) >= 1:
        score += 3
    else:
        issues.append("no recommended_actions provided")

    # --- Apply threshold ---
    if score < REPORT_QUALITY_THRESHOLD:
        issue_str = "; ".join(issues) if issues else "general quality concerns"
        return (
            f"Report quality score {score}/12 is below threshold {REPORT_QUALITY_THRESHOLD}/12. "
            f"Issues: {issue_str}. "
            f"Improve the report: ensure tldr is 1-5 sentences, cite specific data values, "
            f"remove hedge words from conclusions, and add at least one recommended action."
        )
    return None


# =============================================================================
# Rule registry — maps stages to their business rules
# =============================================================================

# Wave 5: QUESTION_PARSE stage (new — runs before UNDERSTAND)
QUESTION_PARSE_RULES: List[Callable] = [
    rule_question_brief_valid,
]

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
    rule_srm_check,  # Wave 5: experiment arm ratio validation
]

SYNTHESIZE_RULES: List[Callable] = [
    rule_all_mandatory_sections_present,
    rule_effect_size_proportionality,
    rule_upgrade_condition_stated,
    rule_mode_compliance_simple,   # Wave 5: simple mode can't have DISPATCH findings
    rule_report_quality_score,     # Wave 5: 12-point report quality rubric
]

# Convenient lookup
STAGE_RULES: Dict[str, List[Callable]] = {
    "QUESTION_PARSE": QUESTION_PARSE_RULES,
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
    domain_rules: Optional[List[Callable]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Validate a stage output against its contract and business rules.

    This is the core enforcement function. It:
    1. Runs all business rules for the stage (generic + domain-specific)
    2. Collects violations
    3. Emits a seam span to the trace (if provided)
    4. Handles the violation according to the stage's gate tier:
       - HARD: raises SeamViolation
       - SOFT: returns result with violations recorded (warns but continues)
       - RETRY: raises SeamViolation (caller handles retry + fallback to soft)

    Args:
        result: The stage output dict to validate
        stage: "QUESTION_PARSE" | "UNDERSTAND" | "HYPOTHESIZE" | "DISPATCH" | "SYNTHESIZE"
        trace: Optional InvestigationTrace to emit seam spans to
        business_rules: Override rules (default: STAGE_RULES[stage])
        domain_rules: Additional domain-specific rules to run alongside
            the base rules. Use this when a domain provides extra validation
            beyond what STAGE_RULES contains. These rules are appended to
            (not replacing) the base rules.
        **kwargs: Additional context passed to rules (e.g., understand_result)

    Returns:
        Dict with keys:
        - passed: bool
        - violations: List[str]
        - tier: str
        - checks: Dict[str, bool] — per-rule results
    """
    rules = business_rules or STAGE_RULES.get(stage, [])
    # Append domain-specific rules if provided (e.g., from domain.get_quality_rules())
    if domain_rules:
        rules = list(rules) + list(domain_rules)
    tier = GATE_TIERS.get(stage, "soft")

    violations = []
    checks = {}

    for rule in rules:
        # Domain rules from get_quality_rules() arrive as dicts
        # {name, stage, check} — extract the callable and name.
        # Built-in rules are plain functions with __name__.
        if isinstance(rule, dict):
            rule_name = rule["name"]
            rule_fn = rule["check"]
        else:
            rule_name = rule.__name__
            rule_fn = rule
        violation = rule_fn(result, **kwargs)
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
            "QUESTION_PARSE": "QuestionBrief",
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

    # LAYER EXCEPTION: contracts/ → harness/ (normally forbidden).
    # WHY: emit_guardrail must run BEFORE the gate tier check below, so it
    # captures GUARDRAIL spans for both passing AND failing validations.
    # Moving to callers would lose failure spans (hard/retry gates raise
    # before the caller can emit). This is a pure observability side-effect
    # with no logic dependency — the import is lazy and no-ops if Phoenix
    # deps aren't installed.
    from harness.phoenix_tracer import emit_guardrail
    emit_guardrail(
        stage=stage,
        passed=passed,
        tier=tier,
        violations=violations,
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
                       choices=["question_parse", "understand", "hypothesize", "dispatch", "synthesize"])
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
        "QUESTION_PARSE": "Question parsing failed. Check that the question type is valid and metric hints are provided for non-adhoc questions.",
        "UNDERSTAND": "Data quality issues detected. Check the input data for missing values, outliers, or insufficient history.",
        "HYPOTHESIZE": "Hypothesis generation did not meet requirements. Ensure at least 3 hypotheses with confirms_if criteria, including one contrarian.",
        "DISPATCH": "Sub-agent findings have issues. Ensure each finding has evidence data (not just narrative) and that narrative matches evidence direction.",
        "SYNTHESIZE": "Report is incomplete. Check that all 7 mandatory sections are filled, language matches severity, and upgrade_condition is stated.",
    }
    return hints.get(stage, "Review the violations and address each one.")


if __name__ == "__main__":
    main()
