"""DISPATCH stage — investigate hypotheses using specialist agents or LLM.

Two modes:
- Sequential (Medium): investigate one hypothesis at a time via LLM or agent callables
- Parallel (Complex): investigate concurrently via DAGExecutor + ThreadPoolExecutor

WHY A STANDALONE MODULE (not methods):
Extracted from SearchMetricOrchestrator._stage_dispatch() and
_stage_dispatch_parallel() to keep the orchestrator small and each
stage independently testable.

Dependencies:
- DomainInterface: domain.get_prompts("dispatch") for prompt builders
- harness.llm: extract_json
- harness.dag_executor: DAGExecutor (parallel mode only)
- contracts.seam_validator: validate_seam
- trace: emit TraceSpan
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from harness.types import LLMCallable

from contracts.seam_validator import validate_seam
from harness.errors import StageError, LLMParseError
from harness.llm import extract_json
from trace.collector import InvestigationTrace
from harness.phoenix_tracer import dual_emit

logger = logging.getLogger(__name__)


def stage_dispatch(
    hypothesis_set: Dict[str, Any],
    understand_result: Dict[str, Any],
    trace: InvestigationTrace,
    llm_callable: LLMCallable,
    config: Dict[str, Any],
    question_type: Optional[str] = None,
    domain=None,  # Optional[DomainInterface] — injected by orchestrator
) -> Dict[str, Any]:
    """Stage 3: DISPATCH (Sequential) — investigate hypotheses one at a time.

    Routes each hypothesis to either:
    - Agent callables (if config["agents"] is provided)
    - LLM callable (default — one call per hypothesis)

    Per-hypothesis error isolation: individual failures produce an
    inconclusive finding (NOT a pipeline halt). Only raises StageError
    if the hypothesis set is empty OR all hypotheses fail.

    Args:
        hypothesis_set: Output from stage_hypothesize() (HypothesisSet dict).
        understand_result: Output from stage_understand().
        trace: InvestigationTrace to record decisions to.
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
        config: Orchestrator config dict (may contain "agents" key).
        question_type: Optional question type for seam validation rules.
        domain: DomainInterface instance providing prompt builders. Defaults to
                SearchMetricsDomain if None (backward-compatible fallback).

    Returns:
        FindingSet dict with keys: findings, context_construction_trace.

    Raises:
        StageError: If hypothesis set is empty or all investigations fail.
    """
    hypotheses = hypothesis_set.get("hypotheses", [])

    # --- Pre-condition: must have at least one hypothesis ---
    if not hypotheses:
        raise StageError(
            message="DISPATCH failed: no hypotheses to investigate.",
            stage="DISPATCH",
            violations=["Empty hypothesis set — nothing to dispatch"],
        )

    # --- Build context for investigators ---
    # Get token-budgeted summary from HYPOTHESIZE stage for context
    hypothesize_context = trace.agent_context_for("HYPOTHESIZE", max_tokens=1500)

    # Build a diagnosis context dict for agent callables
    diagnosis_context = {
        "understand_result": understand_result,
        "hypothesize_context": hypothesize_context,
    }

    # Track what context was given to each investigator (IC9 #3)
    context_construction_log = []

    # --- Investigate each hypothesis ---
    findings = []
    agents = config.get("agents")

    # Resolve prompt builders lazily — only needed for the LLM path.
    # Hoisted above the loop so we pay one get_prompts() call, not N.
    # Skipped entirely when agents are provided (custom domains may
    # not have dispatch prompts at all).
    dispatch_prompts = None
    if not agents:
        if domain is None:
            from domains.search_metrics import SearchMetricsDomain
            domain = SearchMetricsDomain()
        dispatch_prompts = domain.get_prompts("dispatch")

    for hyp in hypotheses:
        hyp_id = hyp.get("hypothesis_id", "unknown")

        try:
            if agents:
                # --- Agent callable path ---
                # Run each agent on this hypothesis, take the first result
                finding = _dispatch_via_agents(
                    agents=agents,
                    diagnosis_context=diagnosis_context,
                    hypothesis=hyp,
                )
            else:
                # --- LLM path ---
                # Pass the pre-resolved dispatch_prompts dict (hoisted above
                # the loop) rather than letting _dispatch_via_llm call
                # domain.get_prompts() itself on every hypothesis.
                finding = _dispatch_via_llm(
                    hypothesis=hyp,
                    understand_result=understand_result,
                    hypothesize_context=hypothesize_context,
                    llm_callable=llm_callable,
                    dispatch_prompts=dispatch_prompts,
                )

            findings.append(finding)
            context_construction_log.append(
                f"Hypothesis {hyp_id}: investigated successfully"
            )

        except Exception as e:
            # Per-hypothesis error isolation: failures -> inconclusive finding.
            # Expected exceptions: LLMAPIError (timeout/rate limit),
            # LLMParseError (bad JSON), StageError (validation failure).
            # We catch broadly because unexpected exceptions should also
            # produce inconclusive findings, not crash the pipeline.
            findings.append({
                "agent_name": "llm_investigator",
                "hypothesis_id": hyp_id,
                "verdict": "inconclusive",
                "confidence": 0.0,
                "evidence": [],
                "narrative": f"Investigation failed: {str(e)[:200]}",
                "adjacent_observations": [],
            })
            context_construction_log.append(
                f"Hypothesis {hyp_id}: investigation failed ({type(e).__name__})"
            )

    # --- Check if ALL hypotheses failed ---
    # If every finding is inconclusive with 0.0 confidence, all failed
    all_failed = all(
        f.get("verdict") == "inconclusive" and f.get("confidence", 1.0) == 0.0
        for f in findings
    )
    if all_failed:
        raise StageError(
            message=(
                f"DISPATCH failed: all {len(hypotheses)} hypothesis investigations "
                f"failed. No evidence was gathered."
            ),
            stage="DISPATCH",
            violations=[
                f"All {len(hypotheses)} investigations failed"
            ],
        )

    # Build the FindingSet result
    context_trace_str = "; ".join(context_construction_log)
    finding_set = {
        "findings": findings,
        "context_construction_trace": context_trace_str,
    }

    # --- Emit IC9 Invisible Decision #3: context_construction ---
    # What context did each investigator receive? This was previously
    # invisible — you saw findings but not what information the
    # investigator was given to work with.
    dual_emit(
        trace,
        stage="DISPATCH",
        swimlane="llm_generated",
        tool="harness.stages.dispatch.stage_dispatch",
        decision="context_construction",
        value={
            "hypotheses_investigated": len(hypotheses),
            "findings_count": len(findings),
            "successful": len([f for f in findings if f.get("confidence", 0) > 0]),
            "inconclusive": len([f for f in findings if f.get("verdict") == "inconclusive"]),
        },
        constrained_by=[
            "rule_each_finding_has_evidence",
            "rule_narrative_data_coherence",
        ],
        human_summary=(
            f"DISPATCH: investigated {len(hypotheses)} hypotheses, "
            f"produced {len(findings)} findings. "
            f"Context: {context_trace_str[:200]}"
        ),
        agent_context=(
            f"hypotheses_investigated={len(hypotheses)}, "
            f"findings_count={len(findings)}, "
            f"context_trace={context_trace_str[:300]}"
        ),
    )

    # --- Seam validation (SOFT gate) ---
    # DISPATCH uses a SOFT gate — if one finding has no evidence,
    # we log it but don't halt. One bad finding shouldn't kill
    # an otherwise useful investigation.
    validation = validate_seam(
        result=finding_set,
        stage="DISPATCH",
        trace=trace,
        question_type=question_type,
    )

    if not validation["passed"]:
        logger.warning(
            "DISPATCH seam validation failed (SOFT gate — continuing): %s",
            "; ".join(validation["violations"]),
        )

    return finding_set


def stage_dispatch_parallel(
    hypothesis_set: Dict[str, Any],
    understand_result: Dict[str, Any],
    trace: InvestigationTrace,
    llm_callable: LLMCallable,
    config: Dict[str, Any],
    question_type: Optional[str] = None,
    domain=None,  # Optional[DomainInterface] — injected by orchestrator
) -> Dict[str, Any]:
    """Stage 3 (Complex mode): Parallel hypothesis investigation via DAGExecutor.

    Uses ThreadPoolExecutor to investigate hypotheses concurrently.
    Each hypothesis gets its own thread with error isolation —
    one failure produces an inconclusive finding, not a pipeline halt.

    Circuit breaker: if 3+ hypotheses fail, raises StageError with
    partial findings available in the error details.

    Args:
        hypothesis_set: Output from stage_hypothesize() (HypothesisSet dict).
        understand_result: Output from stage_understand().
        trace: InvestigationTrace to record decisions to.
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
        config: Orchestrator config dict (timeout, workers, circuit breaker settings).
        question_type: Optional question type for seam validation rules.
        domain: DomainInterface instance providing prompt builders. Defaults to
                SearchMetricsDomain if None (backward-compatible fallback).

    Returns:
        FindingSet dict with keys: findings, context_construction_trace.

    Raises:
        StageError: If hypothesis set is empty or circuit breaker trips.
    """
    from harness.dag_executor import DAGExecutor

    hypotheses = hypothesis_set.get("hypotheses", [])
    if not hypotheses:
        raise StageError(
            message="DISPATCH failed: no hypotheses to investigate.",
            stage="DISPATCH",
            violations=["Empty hypothesis set — nothing to dispatch"],
        )

    hypothesize_context = trace.agent_context_for("HYPOTHESIZE", max_tokens=1500)

    # Build context dict for the investigate function
    dispatch_context = {
        "understand_result": understand_result,
        "hypothesize_context": hypothesize_context,
    }

    # --- Resolve prompt builders once (shared across all parallel threads) ---
    # In parallel mode, N threads all call _dispatch_via_llm concurrently.
    # Resolve get_prompts() once here so threads share the same callable
    # references — no lock contention, no repeated domain work.
    if domain is None:
        from domains.search_metrics import SearchMetricsDomain
        domain = SearchMetricsDomain()
    dispatch_prompts = domain.get_prompts("dispatch")

    # The investigate function wraps _dispatch_via_llm for each hypothesis.
    # dispatch_prompts is captured in the closure so each thread uses the
    # same pre-resolved builders without extra domain calls.
    def investigate_hypothesis(hyp, ctx):
        return _dispatch_via_llm(
            hypothesis=hyp,
            understand_result=ctx["understand_result"],
            hypothesize_context=ctx["hypothesize_context"],
            llm_callable=llm_callable,
            dispatch_prompts=dispatch_prompts,
        )

    executor = DAGExecutor(
        investigate_fn=investigate_hypothesis,
        config={
            "max_workers": config.get("max_dispatch_workers", 5),
            "per_agent_timeout": config.get("timeout_seconds", 60),
            "circuit_breaker_threshold": config.get("circuit_breaker_threshold", 3),
        },
    )

    # DAGExecutor raises StageError if circuit breaker trips
    dag_result = executor.execute(hypotheses, dispatch_context, trace=trace)

    # Build FindingSet from DAG results
    finding_set = {
        "findings": dag_result["findings"],
        "context_construction_trace": (
            f"Parallel dispatch: {len(dag_result['findings'])} findings, "
            f"{dag_result['failed_count']} failures"
        ),
    }

    # Seam validation (SOFT gate)
    # Fix #4: pass question_type so rule_srm_check can activate for experiments
    validation = validate_seam(
        result=finding_set,
        stage="DISPATCH",
        trace=trace,
        question_type=question_type,
    )

    if not validation["passed"]:
        logger.warning(
            "DISPATCH seam validation failed (SOFT gate — continuing): %s",
            "; ".join(validation["violations"]),
        )

    return finding_set


# ---------------------------------------------------------------------------
# Internal dispatch helpers
# ---------------------------------------------------------------------------


def _dispatch_via_agents(
    agents: list,
    diagnosis_context: Dict[str, Any],
    hypothesis: Dict[str, Any],
) -> Dict[str, Any]:
    """Dispatch a hypothesis to agent callables and convert to SubAgentFinding.

    The agent callable signature is (diagnosis_context, hypothesis) -> dict.
    Agent results use the v1 AgentVerdict format, which we convert to
    SubAgentFinding format for the DISPATCH contract.

    Tries agents sequentially — returns the first successful result.
    If an agent crashes, tries the next one. If all agents fail,
    returns an inconclusive finding.
    """
    hyp_id = hypothesis.get("hypothesis_id", "unknown")

    # Try agents sequentially — first success wins.
    # If an agent crashes, try the next one. This prevents a single
    # broken agent from blocking the investigation.
    for agent_fn in agents:
        try:
            agent_result = agent_fn(diagnosis_context, hypothesis)

            # Convert AgentVerdict -> SubAgentFinding.
            # v1 AgentVerdict has no confidence field, so we infer from verdict.
            # TODO(v2): When agent adapters add confidence, use agent_result.get("confidence") directly.
            verdict = agent_result.get("verdict", "inconclusive")
            inferred_confidence = (
                0.75 if verdict == "confirmed"
                else 0.5 if verdict == "rejected"
                else 0.3
            )

            return {
                "agent_name": agent_result.get("agent", "unknown_agent"),
                "hypothesis_id": hyp_id,
                "verdict": verdict,
                "confidence": agent_result.get("confidence", inferred_confidence),
                "evidence": agent_result.get("evidence", []),
                "narrative": agent_result.get("reason", f"Agent investigation of {hyp_id}"),
                "adjacent_observations": [],
            }
        except Exception as e:
            # Agent failed — log a warning and try the next one.
            # Without this log, agent errors are silently swallowed,
            # making debugging impossible when all agents fail.
            agent_name = getattr(agent_fn, "__name__", repr(agent_fn))
            logger.warning("Agent %s failed: %s", agent_name, e)
            continue

    # All agents failed or list was empty
    return {
        "agent_name": "no_agent",
        "hypothesis_id": hyp_id,
        "verdict": "inconclusive",
        "confidence": 0.0,
        "evidence": [],
        "narrative": "No agents were able to investigate this hypothesis.",
        "adjacent_observations": [],
    }


def _dispatch_via_llm(
    hypothesis: Dict[str, Any],
    understand_result: Dict[str, Any],
    hypothesize_context: str,
    llm_callable: LLMCallable,
    dispatch_prompts: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Investigate a single hypothesis using the LLM callable.

    Builds a per-hypothesis prompt, calls the LLM, and parses the
    response into a SubAgentFinding dict.

    Args:
        hypothesis: A single hypothesis dict from HypothesisSet.
        understand_result: Output from stage_understand().
        hypothesize_context: Token-budgeted trace summary from HYPOTHESIZE.
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
        dispatch_prompts: Pre-resolved prompt builder dict from domain.get_prompts("dispatch").
                          Callers (stage_dispatch/stage_dispatch_parallel) resolve this once
                          and pass it in so this function doesn't call domain.get_prompts()
                          on every hypothesis. Falls back to SearchMetricsDomain if None
                          (supports direct calls in tests and legacy code).
    """
    # Prompt builders are resolved by the caller — this avoids N get_prompts()
    # calls for N hypotheses. The fallback handles direct calls to this
    # function (e.g., from tests that bypass stage_dispatch).
    if dispatch_prompts is None:
        from domains.search_metrics import SearchMetricsDomain
        dispatch_prompts = SearchMetricsDomain().get_prompts("dispatch")
    build_dispatch_system_prompt = dispatch_prompts["system_prompt"]
    build_dispatch_user_prompt = dispatch_prompts["user_prompt"]

    hyp_id = hypothesis.get("hypothesis_id", "unknown")

    system_prompt = build_dispatch_system_prompt()
    user_prompt = build_dispatch_user_prompt(
        hypothesis=hypothesis,
        understand_result=understand_result,
        hypothesize_context=hypothesize_context,
    )

    raw_response = llm_callable(user_prompt, system_prompt, 1500)

    try:
        parsed = extract_json(raw_response)
    except LLMParseError as e:
        raise StageError(
            message=(
                f"DISPATCH failed for {hyp_id}: could not extract valid JSON. "
                f"Raw response preview: {str(e.raw_text)[:200]}"
            ),
            stage="DISPATCH",
            violations=[f"JSON extraction failed for hypothesis {hyp_id}"],
        ) from e

    # Normalize the finding — ensure required fields exist
    return {
        "agent_name": parsed.get("agent_name", "llm_investigator"),
        "hypothesis_id": parsed.get("hypothesis_id", hyp_id),
        "verdict": parsed.get("verdict", "inconclusive"),
        "confidence": float(parsed.get("confidence", 0.5)),
        "evidence": parsed.get("evidence", []),
        "narrative": parsed.get("narrative", ""),
        "adjacent_observations": parsed.get("adjacent_observations", []),
    }
