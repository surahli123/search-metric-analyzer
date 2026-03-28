"""Prompt builders for the SearchMetricOrchestrator pipeline stages.

WHY EXTRACTED:
These were originally methods on SearchMetricOrchestrator. Extracting them:
1. Reduces orchestrator.py from ~1,928 to ~1,530 lines (focused on flow, not text)
2. Makes prompts testable without instantiating the full orchestrator
3. Allows run_v2() and agent definitions to reuse the same prompt patterns
4. Enables future per-agent prompt customization (Wave 6)

All functions are pure (no side effects) — they take data in and return strings.
The orchestrator calls these functions; they never call the orchestrator.
"""

from typing import Any, Dict, List


# =============================================================================
# HYPOTHESIZE stage prompts
# =============================================================================

def build_hypothesize_system_prompt() -> str:
    """System prompt for HYPOTHESIZE stage.

    Explains the LLM's role, the AI adoption trap domain rule, the
    hypothesis priority order, and the required JSON output schema.
    """
    return (
        "You are a senior search relevance data scientist diagnosing metric movements "
        "in an Enterprise Search platform (similar to Glean). Your task is to generate "
        "hypotheses that explain a metric movement.\n\n"
        "CRITICAL DOMAIN RULE — AI Adoption Trap:\n"
        "AI answers and clicks have INVERSE co-movement by design. More AI answers → "
        "fewer clicks → Click Quality drops → this is EXPECTED, not a regression. "
        "If Click Quality is down but AI Trigger is up and AI Success is up, "
        "this is a POSITIVE signal. Do NOT generate a 'click_quality_degradation' "
        "hypothesis unless you mark it as contrarian (is_contrarian=True).\n\n"
        "HYPOTHESIS PRIORITY ORDER (fixed — instrumentation first, behavior last):\n"
        "1. Instrumentation/logging anomaly\n"
        "2. Connector/data pipeline change\n"
        "3. Query understanding regression\n"
        "4. Algorithm/model change\n"
        "5. Experiment ramp/de-ramp\n"
        "6. AI feature effect\n"
        "7. Seasonal/external\n"
        "8. User behavior shift (check LAST)\n\n"
        "Return ONLY a valid JSON object matching this schema:\n"
        "{\n"
        '  "hypotheses": [\n'
        "    {\n"
        '      "hypothesis_id": "hyp_001",\n'
        '      "archetype": "ranking_regression",\n'
        '      "priority": 1,\n'
        '      "confirms_if": ["ranking logs show model change in date range"],\n'
        '      "rejects_if": ["no model changes in deployment logs"],\n'
        '      "expected_magnitude": "2-4% drop",\n'
        '      "source": "data_driven",\n'
        '      "is_contrarian": false\n'
        "    }\n"
        "  ],\n"
        '  "exclusions": [\n'
        '    {"archetype": "seasonal", "reason": "No calendar effects match this timing"}\n'
        "  ],\n"
        '  "investigation_context": "summary for downstream stages"\n'
        "}\n\n"
        "REQUIREMENTS:\n"
        "- Generate at least 3 hypotheses\n"
        "- At least one hypothesis MUST have is_contrarian=true\n"
        "- Every hypothesis MUST have non-empty confirms_if and rejects_if\n"
        "- Every hypothesis MUST have expected_magnitude\n"
        "- source must be one of: data_driven, playbook, novel\n"
        "- Include exclusions explaining what you considered but rejected\n"
    )


def build_hypothesize_user_prompt(
    understand_result: Dict[str, Any],
    corrections: List[Dict[str, Any]],
    understand_context: str,
) -> str:
    """User prompt for HYPOTHESIZE stage.

    Provides the LLM with UNDERSTAND output, co-movement pattern,
    mix-shift data, relevant corrections, and trace context.

    Args:
        understand_result: Output from _stage_understand().
        corrections: Relevant past corrections for this metric.
        understand_context: Token-budgeted UNDERSTAND trace context string.

    Returns:
        Formatted user prompt string.
    """
    metric = understand_result.get("metric", "unknown")
    direction = understand_result.get("direction", "unknown")
    severity = understand_result.get("severity", "unknown")
    question = understand_result.get("question", "")

    # Co-movement pattern details
    co_movement = understand_result.get("co_movement_pattern", {})
    pattern_name = co_movement.get("pattern_name", "unknown")
    likely_cause = co_movement.get("likely_cause", "unknown")
    match_score = co_movement.get("match_score", 0)

    sections = []

    # Section 1: Investigation question and metric summary
    sections.append(
        f"INVESTIGATION: {question}\n\n"
        f"METRIC SUMMARY:\n"
        f"  Metric: {metric}\n"
        f"  Direction: {direction}\n"
        f"  Severity: {severity}\n"
    )

    # Section 2: Co-movement pattern
    sections.append(
        f"CO-MOVEMENT PATTERN:\n"
        f"  Pattern: {pattern_name}\n"
        f"  Likely cause: {likely_cause}\n"
        f"  Match score: {match_score}\n"
    )

    # Section 3: Mix-shift result (if present)
    mix_shift = understand_result.get("mix_shift_result")
    if mix_shift and isinstance(mix_shift, dict):
        detected = mix_shift.get("detected", False)
        contribution = mix_shift.get("contribution_pct", 0)
        sections.append(
            f"MIX-SHIFT:\n"
            f"  Detected: {detected}\n"
            f"  Contribution: {contribution:.1%}\n"
            f"  NOTE: If contribution > 25%, you MUST include a mix_shift "
            f"or segment_mix_shift hypothesis.\n"
        )

    # Section 4: Relevant corrections (past mistakes to avoid)
    if corrections:
        correction_lines = ["PAST CORRECTIONS (avoid these mistakes):"]
        for c in corrections[:5]:  # Cap at 5 to stay within token budget
            correction_lines.append(
                f"  - Metric: {c.get('metric')}, "
                f"Originally called: {c.get('original_archetype')}, "
                f"Actually was: {c.get('corrected_to')}\n"
                f"    Context: {c.get('context', 'N/A')}\n"
                f"    Lesson: {c.get('lesson', 'N/A')}"
            )
        sections.append("\n".join(correction_lines))
    else:
        sections.append("PAST CORRECTIONS: None found for this metric.")

    # Section 5: UNDERSTAND stage context (token-budgeted summary from trace)
    sections.append(f"UNDERSTAND STAGE CONTEXT:\n{understand_context}")

    # Section 6: Explicit instruction for contrarian hypothesis
    sections.append(
        "IMPORTANT: Include at least one contrarian hypothesis (is_contrarian=true) "
        "that challenges the most obvious explanation. This prevents confirmation bias."
    )

    return "\n\n".join(sections)


def normalize_hypothesis_set(parsed: Any) -> Dict[str, Any]:
    """Normalize parsed LLM output into a valid HypothesisSet dict.

    Handles malformed data: missing fields, wrong types, lists instead of dicts.
    """
    if isinstance(parsed, list):
        parsed = {"hypotheses": parsed, "exclusions": [], "investigation_context": ""}

    hypotheses = parsed.get("hypotheses", [])
    exclusions = parsed.get("exclusions", [])
    investigation_context = parsed.get("investigation_context", "")

    normalized_hypotheses = []
    for i, h in enumerate(hypotheses):
        normalized_hypotheses.append({
            "hypothesis_id": h.get("hypothesis_id", f"hyp_{i + 1:03d}"),
            "archetype": h.get("archetype", "unknown"),
            "priority": h.get("priority", i + 1),
            "confirms_if": h.get("confirms_if", []),
            "rejects_if": h.get("rejects_if", []),
            "expected_magnitude": h.get("expected_magnitude", ""),
            "source": h.get("source", "novel"),
            "is_contrarian": bool(h.get("is_contrarian", False)),
        })

    normalized_exclusions = []
    for e in exclusions:
        normalized_exclusions.append({
            "archetype": e.get("archetype", "unknown"),
            "reason": e.get("reason", "no reason provided"),
        })

    return {
        "hypotheses": normalized_hypotheses,
        "exclusions": normalized_exclusions,
        "investigation_context": str(investigation_context),
    }


# =============================================================================
# DISPATCH stage prompts
# =============================================================================

def build_dispatch_system_prompt() -> str:
    """System prompt for DISPATCH stage.

    Must contain 'investigating a specific hypothesis' to match the
    test mock LLM routing.
    """
    return (
        "You are a senior search relevance data scientist investigating a specific hypothesis "
        "about why a metric moved in an Enterprise Search platform.\n\n"
        "Your task: investigate the given hypothesis by examining the evidence and "
        "producing a structured finding with your verdict.\n\n"
        "Return a JSON object with these fields:\n"
        "- agent_name (str): 'llm_investigator'\n"
        "- hypothesis_id (str): the hypothesis ID you're investigating\n"
        "- verdict (str): 'confirmed' | 'rejected' | 'inconclusive'\n"
        "- confidence (float): 0.0 to 1.0\n"
        "- evidence (list): raw data citations [{metric, value, delta, direction}]\n"
        "- narrative (str): human-readable explanation of your investigation\n"
        "- adjacent_observations (list of str): unexpected findings\n"
        "- srm_check (dict, optional): for experiment hypotheses only — include if\n"
        "  investigating an A/B test. Fields: expected_ratio (float, typically 0.5),\n"
        "  actual_ratio (float). Omit this field for non-experiment investigations.\n\n"
        "CRITICAL: Every finding MUST include at least one evidence item with real "
        "data values. A finding without evidence is an opinion, not a diagnosis."
    )


def build_dispatch_user_prompt(
    hypothesis: Dict[str, Any],
    understand_result: Dict[str, Any],
    hypothesize_context: str,
) -> str:
    """Per-hypothesis user prompt for DISPATCH."""
    hyp_id = hypothesis.get("hypothesis_id", "unknown")
    archetype = hypothesis.get("archetype", "unknown")
    confirms_if = hypothesis.get("confirms_if", [])
    rejects_if = hypothesis.get("rejects_if", [])

    direction = understand_result.get("direction", "unknown")
    severity = understand_result.get("severity", "unknown")
    metric = understand_result.get("metric", "unknown")

    sections = [
        f"HYPOTHESIS TO INVESTIGATE:",
        f"ID: {hyp_id}",
        f"Archetype: {archetype}",
        f"Confirms if: {', '.join(confirms_if) if confirms_if else 'N/A'}",
        f"Rejects if: {', '.join(rejects_if) if rejects_if else 'N/A'}",
        "",
        f"UNDERSTAND CONTEXT:",
        f"Metric: {metric}, Direction: {direction}, Severity: {severity}",
    ]

    if hypothesize_context:
        sections.append(f"\nHYPOTHESIZE CONTEXT:\n{hypothesize_context}")

    return "\n".join(sections)


# =============================================================================
# SYNTHESIZE stage prompts
# =============================================================================

def build_synthesize_system_prompt() -> str:
    """System prompt for SYNTHESIZE stage.

    Must contain 'final' and 'investigation report' to match the
    test mock LLM routing.
    """
    return (
        "You are a senior search relevance data scientist writing the final "
        "investigation report for a metric movement in an Enterprise Search platform.\n\n"
        "Produce a complete, structured JSON report with these mandatory sections:\n"
        "1. tldr (str): 3 sentences max summarizing the finding\n"
        "2. confidence_grade (str): 'High' | 'Medium' | 'Low'\n"
        "3. severity (str): 'P0' | 'P1' | 'P2' | 'normal'\n"
        "4. root_cause (str): primary explanation for the metric movement\n"
        "5. dimensional_breakdown (str): which dimensions drove the movement\n"
        "6. hypothesis_and_evidence (str): what was investigated and found\n"
        "7. validation_summary (str): cross-checks and coherence\n\n"
        "Additional required fields:\n"
        "- recommended_actions (list): [{action, owner, priority, rationale}]\n"
        "- upgrade_condition (str): 'Would upgrade to X if Y'\n"
        "- completeness_warnings (list of str): known gaps (empty if none)\n\n"
        "STATISTICAL HONESTY RULES:\n"
        "- Use raw n only, no fake confidence intervals\n"
        "- Hedge when n < 500\n"
        "- Never fabricate statistical outputs\n\n"
        "EFFECT-SIZE PROPORTIONALITY:\n"
        "- If severity is P0, do NOT use minimizing words (minor, slight, small)\n"
        "- Language must match severity — P0 is a critical incident"
    )


def build_synthesize_user_prompt(
    understand_result: Dict[str, Any],
    hypothesize_result: Dict[str, Any],
    dispatch_result: Dict[str, Any],
    dispatch_context: str,
) -> str:
    """User prompt for SYNTHESIZE stage."""
    direction = understand_result.get("direction", "unknown")
    severity = understand_result.get("severity", "unknown")
    metric = understand_result.get("metric", "unknown")

    hypotheses = hypothesize_result.get("hypotheses", [])
    hyp_summary = "\n".join([
        f"  - {h.get('archetype', '?')} (priority {h.get('priority', '?')}): "
        f"{h.get('hypothesis_id', '?')}"
        for h in hypotheses
    ])

    findings = dispatch_result.get("findings", [])
    findings_summary = "\n".join([
        f"  - {f.get('hypothesis_id', '?')}: verdict={f.get('verdict', '?')}, "
        f"confidence={f.get('confidence', '?')}"
        for f in findings
    ])

    sections = [
        f"INVESTIGATION SUMMARY:",
        f"Metric: {metric}, Direction: {direction}, Severity: {severity}",
        "",
        f"HYPOTHESES INVESTIGATED:",
        hyp_summary,
        "",
        f"DISPATCH FINDINGS:",
        findings_summary,
        "",
        f"DISPATCH CONTEXT:",
        dispatch_context if dispatch_context else "No context available.",
    ]

    return "\n".join(sections)


def build_synthesize_retry_prompt(
    original_prompt: str,
    violations: List[str],
) -> str:
    """Retry prompt for SYNTHESIZE with violation feedback."""
    violation_text = "\n".join([f"  - {v}" for v in violations])
    return (
        f"{original_prompt}\n\n"
        f"IMPORTANT: Your previous response had issues that MUST be fixed:\n"
        f"{violation_text}\n\n"
        f"Please regenerate the complete report addressing ALL of the above issues."
    )


def normalize_synthesis_report(parsed: Dict, trace_id: str) -> Dict[str, Any]:
    """Normalize a parsed LLM response into SynthesisReport shape."""
    return {
        "tldr": str(parsed.get("tldr", "")),
        "confidence_grade": str(parsed.get("confidence_grade", "")),
        "severity": str(parsed.get("severity", "")),
        "root_cause": str(parsed.get("root_cause", "")),
        "dimensional_breakdown": str(parsed.get("dimensional_breakdown", "")),
        "hypothesis_and_evidence": str(parsed.get("hypothesis_and_evidence", "")),
        "validation_summary": str(parsed.get("validation_summary", "")),
        "recommended_actions": parsed.get("recommended_actions", []),
        "upgrade_condition": str(parsed.get("upgrade_condition", "")),
        "investigation_id": trace_id,
        "completeness_warnings": parsed.get("completeness_warnings", []),
    }
