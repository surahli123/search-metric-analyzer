"""Trace schema validation — verifies trace completeness and correctness.

Used by the eval framework to check that investigations produce complete traces.
The key check is IC9 coverage: all 4 Invisible Decisions must have trace spans.
"""

from typing import Dict, List, Optional, Tuple

# The 4 IC9 Invisible Decisions that must be traced
IC9_INVISIBLE_DECISIONS = [
    "metric_direction",        # UNDERSTAND: which way did the metric move?
    "hypothesis_inclusion",    # HYPOTHESIZE: which hypotheses were kept/dropped?
    "context_construction",    # DISPATCH: what context was given to sub-agents?
    "narrative_selection",     # SYNTHESIZE: which narrative framing was chosen?
]

# The 4 stages that must have seam validation
REQUIRED_SEAMS = ["UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"]


def validate_trace_completeness(trace_dict: Dict) -> Tuple[bool, List[str]]:
    """Check that a trace has all required IC9 spans and seam validations.

    Returns:
        (passed, issues): True if complete, list of issues if not.

    Used by eval/run_eval.py to verify trace coverage after each scenario.
    """
    issues = []

    # Check IC9 Invisible Decisions
    traced_decisions = set(trace_dict.get("summary", {}).get(
        "invisible_decisions_traced", []
    ))
    for decision in IC9_INVISIBLE_DECISIONS:
        if decision not in traced_decisions:
            issues.append(
                f"Missing IC9 Invisible Decision trace: {decision}"
            )

    # Check seam validations
    seam_stages = set(
        s["stage"] for s in trace_dict.get("seam_validations", [])
    )
    for stage in REQUIRED_SEAMS:
        if stage not in seam_stages:
            issues.append(
                f"Missing seam validation for stage: {stage}"
            )

    # Check that at least one span exists per stage
    span_stages = set(
        s.get("stage", "unknown") for s in trace_dict.get("spans", [])
    )
    for stage in REQUIRED_SEAMS:
        if stage not in span_stages:
            issues.append(
                f"No decision spans found for stage: {stage}"
            )

    return (len(issues) == 0, issues)


def validate_span_fields(span: Dict) -> Tuple[bool, List[str]]:
    """Validate that a span has all required fields populated.

    Required fields: trace_id, stage, swimlane, tool, timestamp_ms.
    Optional but recommended: decision, value, human_summary, agent_context.
    """
    issues = []
    required = ["trace_id", "stage", "swimlane", "tool", "timestamp_ms"]

    for field in required:
        if field not in span or span[field] is None:
            issues.append(f"Missing required field: {field}")

    # Validate stage is a known value
    valid_stages = {"UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"}
    if span.get("stage") and span["stage"] not in valid_stages:
        issues.append(
            f"Invalid stage '{span['stage']}'. Must be one of: {valid_stages}"
        )

    # Validate swimlane is a known value
    valid_swimlanes = {"deterministic", "llm_generated", "hybrid"}
    if span.get("swimlane") and span["swimlane"] not in valid_swimlanes:
        issues.append(
            f"Invalid swimlane '{span['swimlane']}'. "
            f"Must be one of: {valid_swimlanes}"
        )

    # For LLM spans, prefer constrained_by over alternatives_considered
    # (IC9 review finding: self-reported alternatives are unreliable)
    if span.get("swimlane") == "llm_generated":
        if span.get("alternatives_considered") and not span.get("constrained_by"):
            issues.append(
                "LLM span has alternatives_considered but no constrained_by. "
                "For LLM spans, constrained_by (verifiable rules) is preferred "
                "over alternatives_considered (self-reported, unreliable)."
            )

    return (len(issues) == 0, issues)
