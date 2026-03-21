"""SYNTHESIZE stage — produce the final investigation report.

Builds a prompt from all prior stages, calls the LLM, and validates
the report against the SynthesisReport contract.

Uses RETRY(1) then SOFT gate:
- First attempt: validate with seam_validator
- If fails: retry once with violations appended to prompt
- If second attempt also fails: continue with completeness_warnings

WHY A STANDALONE FUNCTION (not a method):
Extracted from SearchMetricOrchestrator._stage_synthesize() to keep
the orchestrator small and each stage independently testable.

Dependencies:
- harness.prompts: build_synthesize_* prompt functions, normalize_synthesis_report
- harness.llm: extract_json
- contracts.seam_validator: validate_seam
- trace: emit TraceSpan
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from harness.types import LLMCallable

from contracts.seam_validator import validate_seam, SeamViolation
from harness.errors import StageError, LLMParseError
from harness.llm import extract_json
from trace.collector import InvestigationTrace
from trace.span import TraceSpan

logger = logging.getLogger(__name__)


def stage_synthesize(
    dispatch_result: Dict[str, Any],
    understand_result: Dict[str, Any],
    hypothesize_result: Dict[str, Any],
    trace: InvestigationTrace,
    llm_callable: LLMCallable,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage 4: SYNTHESIZE — produce the final investigation report.

    Uses RETRY(1) then SOFT gate:
    - First attempt: validate with seam_validator
    - If fails: retry once with violations appended to prompt
    - If second attempt also fails: continue with completeness_warnings
      (expensive investigation work is NOT discarded)

    Args:
        dispatch_result: Output from stage_dispatch() (FindingSet dict).
        understand_result: Output from stage_understand().
        hypothesize_result: Output from stage_hypothesize().
        trace: InvestigationTrace to record decisions to.
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
        mode: Pipeline mode ("medium" or "complex") for seam validation.

    Returns:
        SynthesisReport dict with 7 mandatory sections + metadata.

    Raises:
        StageError: If JSON extraction from LLM response fails on both attempts.
    """
    from harness.prompts import (
        build_synthesize_system_prompt,
        build_synthesize_user_prompt,
        build_synthesize_retry_prompt,
        normalize_synthesis_report,
    )

    system_prompt = build_synthesize_system_prompt()
    dispatch_context = trace.agent_context_for("DISPATCH", max_tokens=1500)
    user_prompt = build_synthesize_user_prompt(
        understand_result=understand_result,
        hypothesize_result=hypothesize_result,
        dispatch_result=dispatch_result,
        dispatch_context=dispatch_context,
    )

    # --- First attempt ---
    raw_response = llm_callable(user_prompt, system_prompt, 3000)

    try:
        report = extract_json(raw_response)
    except LLMParseError as e:
        raise StageError(
            message=(
                f"SYNTHESIZE failed: could not extract valid JSON from LLM response. "
                f"Raw response preview: {str(e.raw_text)[:200]}"
            ),
            stage="SYNTHESIZE",
            violations=["LLM response did not contain parseable JSON"],
        ) from e

    # Normalize the report — ensure all expected fields exist
    report = normalize_synthesis_report(report, trace.trace_id)

    # Save the first attempt so we can fall back to it if retry also fails.
    # (I1 fix: explicit save prevents stale variable bugs in the retry path.)
    first_attempt_report = report

    # --- RETRY(1) then SOFT validation gate ---
    # validate_seam raises SeamViolation for "retry" tier.
    # We catch it, retry once, then fall back to soft if the retry also fails.
    completeness_warnings = []

    try:
        validation = validate_seam(
            result=report,
            stage="SYNTHESIZE",
            trace=trace,
            mode=mode,
        )
    except SeamViolation as first_violation:
        # First attempt failed — retry with violation feedback
        logger.warning(
            "SYNTHESIZE first attempt failed validation — retrying: %s",
            "; ".join(first_violation.violations),
        )

        # Build retry prompt with violations appended
        retry_prompt = build_synthesize_retry_prompt(
            original_prompt=user_prompt,
            violations=first_violation.violations,
        )

        # --- Second attempt (retry) ---
        raw_response_2 = llm_callable(retry_prompt, system_prompt, 3000)

        try:
            report = extract_json(raw_response_2)
        except LLMParseError:
            # Second attempt also failed to produce valid JSON.
            # Fall back to the first attempt's report with warnings.
            report = first_attempt_report
            completeness_warnings.append(
                f"SEAM VIOLATION: retry also failed to produce valid JSON. "
                f"Using first attempt with known deficiencies: "
                f"{'; '.join(first_violation.violations)}"
            )
            report["completeness_warnings"] = completeness_warnings
            # Still emit trace and return (soft fallback)
            _emit_synthesize_trace(report, trace)
            return report

        report = normalize_synthesis_report(report, trace.trace_id)

        # Validate the retry result
        try:
            validation = validate_seam(
                result=report,
                stage="SYNTHESIZE",
                trace=trace,
                mode=mode,
            )
        except SeamViolation as second_violation:
            # Both attempts failed — SOFT fallback.
            # Don't discard expensive investigation work.
            # Add completeness_warnings so the reader knows the report
            # has known deficiencies.
            for v in second_violation.violations:
                completeness_warnings.append(f"SEAM VIOLATION: {v}")
            logger.warning(
                "SYNTHESIZE retry also failed validation — "
                "continuing with best-effort report: %s",
                "; ".join(second_violation.violations),
            )

    # Apply any accumulated warnings
    if completeness_warnings:
        report["completeness_warnings"] = completeness_warnings

    # --- Emit IC9 Invisible Decision #4: narrative_selection ---
    _emit_synthesize_trace(report, trace)

    return report


def _emit_synthesize_trace(report: Dict[str, Any], trace: InvestigationTrace) -> None:
    """Emit IC9 Invisible Decision #4: narrative_selection.

    Records what narrative framing the LLM chose for the report.
    Previously invisible — you saw the report but not why the LLM
    chose that particular confidence grade, severity, or framing.
    """
    trace.emit(TraceSpan(
        stage="SYNTHESIZE",
        swimlane="llm_generated",
        tool="harness.stages.synthesize.stage_synthesize",
        decision="narrative_selection",
        code_enforced=False,
        value={
            "confidence_grade": report.get("confidence_grade", ""),
            "severity": report.get("severity", ""),
            "action_count": len(report.get("recommended_actions", [])),
            "has_upgrade_condition": bool(report.get("upgrade_condition")),
        },
        constrained_by=[
            "rule_all_mandatory_sections_present",
            "rule_effect_size_proportionality",
            "rule_upgrade_condition_stated",
        ],
        human_summary=(
            f"SYNTHESIZE: {report.get('confidence_grade', '?')} confidence, "
            f"{report.get('severity', '?')} severity, "
            f"{len(report.get('recommended_actions', []))} actions recommended. "
            f"Upgrade condition: {'stated' if report.get('upgrade_condition') else 'missing'}."
        ),
        agent_context=(
            f"confidence_grade={report.get('confidence_grade', '')}, "
            f"severity={report.get('severity', '')}, "
            f"action_count={len(report.get('recommended_actions', []))}, "
            f"has_upgrade_condition={bool(report.get('upgrade_condition'))}"
        ),
    ))
