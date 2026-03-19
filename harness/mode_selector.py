"""Mode selector — routes questions to Simple/Medium/Complex investigation modes.

WHY THIS EXISTS:
The current pipeline runs the same 4-stage flow regardless of question complexity.
"What's the CQ formula?" shouldn't trigger a full investigation with hypotheses
and sub-agents — it should be a direct knowledge lookup. Conversely, a P0
multi-metric regression needs the full pipeline with parallel sub-agent dispatch.

DESIGN DECISION: Rule-based, not LLM-assisted.
Same rationale as question_parser: runs BEFORE any LLM call, must be deterministic
and testable. The routing rules below are documented and can be audited.

MODES:
- Simple: Direct knowledge lookup. No pipeline stages. ~5K tokens.
  Example: "What's the Click Quality formula?"

- Medium: Standard 4-stage pipeline (current SMA behavior). ~20K tokens.
  Example: "CQ dropped 2% last week — is this expected?"

- Complex: Full pipeline + parallel sub-agent dispatch in DISPATCH stage. ~40K tokens.
  Example: "Multiple metrics degraded overnight — P0 investigation needed"

ANALOGY: This is like traffic routing in a load balancer — lightweight requests
go to a fast path, heavy requests get the full processing pipeline.
"""

from typing import Any, Dict, Optional

from trace.helpers import emit_deterministic_span


# =============================================================================
# Mode definitions
# =============================================================================

MODES = {
    "simple": {
        "agent_file": "agents/lead-agent-simple.md",
        "description": "Direct knowledge lookup, no pipeline stages",
        "max_tokens": 5000,
        "stages": [],  # No pipeline stages — direct answer
    },
    "medium": {
        "agent_file": "agents/lead-agent-medium.md",
        "description": "Standard 4-stage pipeline",
        "max_tokens": 20000,
        "stages": ["UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"],
    },
    "complex": {
        "agent_file": "agents/lead-agent-complex.md",
        "description": "Full pipeline with parallel sub-agent dispatch",
        "max_tokens": 40000,
        "stages": ["UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"],
    },
}


# =============================================================================
# Routing rules
# =============================================================================

# Maps (question_type, conditions) → mode
# Conditions are checked against the QuestionBrief dict.
# Rules are evaluated top-to-bottom; first match wins.

def _has_severity_signal(brief: Dict, severities: set) -> bool:
    """Check if the question brief contains specific severity signals."""
    for signal in brief.get("complexity_signals", []):
        if any(sev in signal.lower() for sev in severities):
            return True
    return False


def _has_multiple_metrics(brief: Dict) -> bool:
    """Check if the question references more than one metric."""
    return len(brief.get("metric_hints", [])) > 1


def select_mode(
    question_brief: Dict[str, Any],
    override_mode: Optional[str] = None,
    trace=None,
) -> Dict[str, Any]:
    """Select investigation mode based on the question brief.

    Routing rules (evaluated in order):
    1. adhoc → Simple (always — it's a lookup)
    2. sev + P0/P1 severity signals → Complex (high stakes, need full investigation)
    3. sev + P2/normal → Medium (standard diagnostic)
    4. experiment + multiple metrics → Complex (interaction effects)
    5. experiment → Medium (standard evaluation)
    6. deep_dive → Complex (always — user explicitly wants comprehensive analysis)
    7. trend → Medium (longitudinal analysis, not urgent)
    8. system_understanding → Medium (analytical, not diagnostic)
    9. fallback → Medium (safe default)

    Args:
        question_brief: QuestionBrief dict from parse_question().
        override_mode: Optional mode override (e.g., user says "run complex").
            Must be one of "simple", "medium", "complex".
        trace: Optional InvestigationTrace for recording the decision.

    Returns:
        ModeDecision dict with keys:
        - mode: "simple" | "medium" | "complex"
        - confidence: 0.0-1.0 (how confident the routing is)
        - reasoning: Human-readable explanation of why this mode was chosen
        - agent_file: Path to the lead agent .md file for this mode
    """
    # --- Override takes precedence ---
    if override_mode:
        if override_mode not in MODES:
            # Invalid override — fall back to medium with warning
            mode = "medium"
            confidence = 0.5
            reasoning = (
                f"Override '{override_mode}' is invalid "
                f"(must be one of {sorted(MODES.keys())}). "
                f"Falling back to medium mode."
            )
        else:
            mode = override_mode
            confidence = 1.0
            reasoning = f"User override: {override_mode}"
    else:
        # --- Apply routing rules ---
        mode, confidence, reasoning = _apply_routing_rules(question_brief)

    # Build the ModeDecision
    mode_info = MODES[mode]
    decision = {
        "mode": mode,
        "confidence": confidence,
        "reasoning": reasoning,
        "agent_file": mode_info["agent_file"],
    }

    # --- Emit trace span ---
    emit_deterministic_span(
        trace,
        tool="harness.mode_selector.select_mode",
        decision="mode_selection",
        value=mode,
        stage="QUESTION_PARSE",
        human_summary=(
            f"Mode selected: {mode} (confidence={confidence:.0%}). "
            f"Reason: {reasoning}"
        ),
        agent_context=(
            f"mode={mode}, confidence={confidence}, "
            f"agent_file={mode_info['agent_file']}, "
            f"question_type={question_brief.get('question_type', 'unknown')}"
        ),
    )

    return decision


def _apply_routing_rules(brief: Dict[str, Any]) -> tuple:
    """Apply routing rules to determine mode.

    Returns (mode, confidence, reasoning) tuple.
    """
    q_type = brief.get("question_type", "adhoc")

    # Rule 1: adhoc → Simple
    if q_type == "adhoc":
        return "simple", 0.95, "Adhoc question — direct knowledge lookup, no investigation needed"

    # Rule 2: sev + P0/P1 → Complex
    if q_type == "sev" and _has_severity_signal(brief, {"p0", "critical", "incident"}):
        return "complex", 0.90, "SEV with P0/critical severity — full investigation with parallel dispatch"

    if q_type == "sev" and _has_severity_signal(brief, {"p1", "significant"}):
        return "complex", 0.85, "SEV with P1/significant severity — full investigation warranted"

    # Rule 3: sev + P2/normal → Medium
    if q_type == "sev":
        return "medium", 0.85, "SEV with P2/normal severity — standard diagnostic pipeline"

    # Rule 4: experiment + multiple metrics → Complex
    if q_type == "experiment" and _has_multiple_metrics(brief):
        return "complex", 0.80, "Experiment with multiple metrics — need interaction effect analysis"

    # Rule 5: experiment → Medium
    if q_type == "experiment":
        return "medium", 0.85, "Experiment evaluation — standard pipeline with SRM check"

    # Rule 6: deep_dive → Complex
    if q_type == "deep_dive":
        return "complex", 0.90, "Deep dive requested — comprehensive analysis with full sub-agent dispatch"

    # Rule 7: trend → Medium
    if q_type == "trend":
        return "medium", 0.85, "Trend analysis — longitudinal pipeline, no urgency"

    # Rule 8: system_understanding → Medium
    if q_type == "system_understanding":
        return "medium", 0.80, "System understanding — analytical, knowledge-heavy"

    # Rule 9: fallback → Medium
    return "medium", 0.60, f"Unrecognized question type '{q_type}' — defaulting to medium mode"
