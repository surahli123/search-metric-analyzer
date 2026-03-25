"""HYPOTHESIZE stage — LLM generates hypotheses from UNDERSTAND results.

Returns a HypothesisSet dict conforming to contracts/hypothesize.py schema.

WHY A STANDALONE FUNCTION (not a method):
Extracted from SearchMetricOrchestrator._stage_hypothesize() to keep
the orchestrator class small and each stage independently testable.
The LLM callable is passed as an explicit parameter.

Dependencies:
- core.corrections: load_corrections, find_relevant_corrections
- domains.search_metrics.prompts: build_hypothesize_* prompt functions, normalize_hypothesis_set
- harness.llm: extract_json
- contracts.seam_validator: validate_seam
- trace: emit TraceSpan
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from harness.types import LLMCallable

from core.corrections import load_corrections, find_relevant_corrections
from contracts.seam_validator import validate_seam
from harness.errors import StageError, LLMParseError
from harness.llm import extract_json
from trace.collector import InvestigationTrace
from harness.phoenix_tracer import dual_emit

logger = logging.getLogger(__name__)


def stage_hypothesize(
    understand_result: Dict[str, Any],
    trace: InvestigationTrace,
    llm_callable: LLMCallable,
) -> Dict[str, Any]:
    """Stage 2: HYPOTHESIZE — LLM generates hypotheses from UNDERSTAND results.

    Steps:
    1. Load corrections from corrections.yaml (past diagnostic mistakes)
    2. Build system + user prompt with UNDERSTAND context + corrections
    3. Call the LLM to generate 3+ hypotheses as JSON
    4. Parse JSON response using extract_json()
    5. Emit IC9 Invisible Decision #2 trace span (hypothesis_inclusion)
    6. Validate with seam_validator (SOFT gate — log violations, continue)
    7. Return HypothesisSet dict

    Error handling:
    - LLMAPIError (transient): propagates up to caller (retry handled externally)
    - LLMParseError: wrapped in StageError with stage="HYPOTHESIZE"
    - Seam validation failure: logged in trace but pipeline continues (SOFT gate)

    Args:
        understand_result: Output from stage_understand().
        trace: InvestigationTrace to record decisions to.
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.

    Returns:
        HypothesisSet dict with keys: hypotheses, exclusions, investigation_context.

    Raises:
        StageError: If JSON extraction from LLM response fails.
        LLMAPIError: If LLM call fails with a transient error (propagates).
    """
    from domains.search_metrics.prompts import (
        build_hypothesize_system_prompt,
        build_hypothesize_user_prompt,
        normalize_hypothesis_set,
    )

    # --- Step 1: Load corrections (past diagnostic mistakes to avoid) ---
    # We load corrections for the current metric so the LLM knows what
    # mistakes were made before and can avoid repeating them.
    # Empty list is fine — new installs won't have corrections yet.
    metric = understand_result.get("metric", "")
    # Use the co-movement pattern's likely_cause as the "current archetype"
    # for finding relevant corrections. This surfaces corrections from
    # similar past situations.
    co_movement = understand_result.get("co_movement_pattern", {})
    current_archetype = co_movement.get("likely_cause", "unknown")
    all_corrections = load_corrections()
    relevant_corrections = find_relevant_corrections(
        metric=metric,
        archetype=current_archetype,
        corrections=all_corrections,
    )

    # --- Step 2: Build prompts ---
    system_prompt = build_hypothesize_system_prompt()
    understand_context = trace.agent_context_for("UNDERSTAND")
    user_prompt = build_hypothesize_user_prompt(
        understand_result=understand_result,
        corrections=relevant_corrections,
        understand_context=understand_context,
    )

    # --- Step 3: Call the LLM ---
    # LLMAPIError (transient) will propagate up — the caller
    # (or _call_with_retry if used) handles retry logic.
    raw_response = llm_callable(user_prompt, system_prompt, 2000)

    # --- Step 4: Parse JSON from LLM response ---
    # If the LLM returns unparseable output, wrap in StageError.
    # This is a persistent error — retrying the same prompt usually
    # produces the same broken output.
    try:
        parsed = extract_json(raw_response)
    except LLMParseError as e:
        raise StageError(
            message=(
                f"HYPOTHESIZE failed: could not extract valid JSON from LLM response. "
                f"Raw response preview: {str(e.raw_text)[:200]}"
            ),
            stage="HYPOTHESIZE",
            violations=["LLM response did not contain parseable JSON"],
            details={"raw_response_preview": str(e.raw_text)[:500]},
        ) from e

    # --- Step 4b: Normalize the parsed result into HypothesisSet shape ---
    hypothesis_set = normalize_hypothesis_set(parsed)

    # --- Step 5: Emit IC9 Invisible Decision #2 trace span ---
    # hypothesis_inclusion: what hypotheses were included/excluded and why.
    # This makes the LLM's selection process auditable — previously this
    # was invisible (you only saw the final list, not what was considered).
    included_archetypes = [
        h.get("archetype", "unknown") for h in hypothesis_set.get("hypotheses", [])
    ]
    excluded_archetypes = [
        e.get("archetype", "unknown") for e in hypothesis_set.get("exclusions", [])
    ]
    exclusion_reasons = [
        f"{e.get('archetype', '?')}: {e.get('reason', 'no reason given')}"
        for e in hypothesis_set.get("exclusions", [])
    ]

    # Dual-emit: writes to InvestigationTrace AND OTel (if Phoenix available)
    dual_emit(
        trace,
        stage="HYPOTHESIZE",
        swimlane="llm_generated",
        tool="harness.stages.hypothesize.stage_hypothesize",
        decision="hypothesis_inclusion",
        value={
            "included": included_archetypes,
            "excluded": excluded_archetypes,
        },
        constrained_by=[
            "rule_min_three_hypotheses",
            "rule_has_contrarian_hypothesis",
            "rule_hypotheses_consistent_with_co_movement",
            "rule_mix_shift_considered_when_detected",
        ],
        human_summary=(
            f"HYPOTHESIZE: {len(included_archetypes)} hypotheses generated, "
            f"{len(excluded_archetypes)} excluded. "
            f"Included: {', '.join(included_archetypes)}. "
            f"Excluded: {'; '.join(exclusion_reasons) if exclusion_reasons else 'none'}."
        ),
        agent_context=(
            f"hypotheses_count={len(included_archetypes)}, "
            f"exclusions_count={len(excluded_archetypes)}, "
            f"included_archetypes={included_archetypes}, "
            f"has_contrarian={any(h.get('is_contrarian') for h in hypothesis_set.get('hypotheses', []))}"
        ),
    )

    # --- Step 6: Seam validation (SOFT gate) ---
    # HYPOTHESIZE uses a SOFT gate — if validation fails, we log the
    # violations in the trace but continue with whatever hypotheses exist.
    # Rationale: a DS debugging a P0 needs *something*. 2 hypotheses with
    # a warning is better than nothing.
    validation = validate_seam(
        result=hypothesis_set,
        stage="HYPOTHESIZE",
        trace=trace,
        # Pass understand_result for cross-stage rules (Amendments 2 & 3):
        # - rule_hypotheses_consistent_with_co_movement needs co_movement_pattern
        # - rule_mix_shift_considered_when_detected needs mix_shift_result
        understand_result=understand_result,
    )

    # SOFT gate: if validation failed, log a warning but DON'T halt.
    # The violations are already recorded in the trace via validate_seam().
    if not validation["passed"]:
        logger.warning(
            "HYPOTHESIZE seam validation failed (SOFT gate — continuing): %s",
            "; ".join(validation["violations"]),
        )

    # --- Step 7: Return the HypothesisSet ---
    return hypothesis_set
