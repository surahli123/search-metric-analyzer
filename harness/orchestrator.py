"""Multi-agent orchestrator — post-process hook for diagnosis verification.

WHY THIS MODULE EXISTS:
The diagnosis pipeline (core/diagnose.py) produces a single hypothesis about
why a metric moved.  That hypothesis might be wrong.  The orchestrator runs
specialist agents AFTER the diagnosis to verify (or challenge) the hypothesis,
then fuses their individual verdicts into a single decision.

ARCHITECTURE PATTERN: Post-Process Hook
The orchestrator NEVER modifies the diagnosis result dict.  It only READS
the diagnosis and RETURNS a new OrchestrationResult dict.  The caller decides
whether to merge the result back.  This keeps the orchestrator completely
decoupled from the diagnosis pipeline — you can use it or skip it.

Think of it like a code review step in a CI pipeline: the build already
produced an artifact, and the reviewers either approve or reject it.
The reviewers don't rewrite the artifact.

EXECUTION MODEL: Sequential
Agents run one at a time, in the order provided.  This is intentionally
simple — easy to reason about, easy to debug.  Parallelism can be added
later if/when latency becomes a problem.  (YAGNI: don't optimize before
you have evidence that sequential is too slow.)

FUSION POLICY: Deterministic Priority
Individual verdicts are combined using a strict priority order:
    blocked > rejected > confirmed > inconclusive
No ML, no voting weights — just clear, debuggable rules.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

# Cross-package dependency: schema.py lives in core/, not harness/.
from core.schema import normalize_agent_verdict, VALID_VERDICTS


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default orchestration settings.
# max_agents:              Cap on how many agents run per diagnosis.
#                          Prevents runaway cost if someone registers 50 agents.
# global_timeout_seconds:  Hard wall-clock limit for the entire orchestration.
#                          Prevents one slow agent from blocking everything.
DEFAULT_CONFIG: Dict[str, Any] = {
    "max_agents": 4,
    "global_timeout_seconds": 300,
}


# ---------------------------------------------------------------------------
# Gate Logic
# ---------------------------------------------------------------------------

def _should_orchestrate(diagnosis_result: Dict[str, Any], agents: list) -> bool:
    """Decide whether to run specialist agents against this diagnosis.

    Gate conditions (ALL must be true):
    1. decision_status == "diagnosed"   — only verified diagnoses get agents
    2. confidence != "High"             — high confidence doesn't need verification
    3. agents list is non-empty         — nothing to run with no agents

    WHY gate at all?
    Running agents has a cost (time, API calls, compute).  If the diagnosis
    is already high-confidence, or if it failed before reaching a conclusion,
    there's no point in running additional checks.  This is the same logic
    as skipping expensive A/B test analysis when sample size is too small.

    Args:
        diagnosis_result: The completed diagnosis dict from run_diagnosis().
        agents:           List of agent callables to potentially run.

    Returns:
        True if orchestration should proceed, False to skip.
    """
    # No agents registered → nothing to do.
    if not agents:
        return False

    # Only run agents when the diagnosis actually reached a conclusion.
    # Other statuses like "insufficient_evidence" or "blocked_by_data_quality"
    # mean the diagnosis itself couldn't complete, so verifying it is pointless.
    decision_status = diagnosis_result.get("decision_status", "")
    if decision_status != "diagnosed":
        return False

    # High confidence means the diagnosis is already strong.
    # Running agents would be wasted effort — like running a full regression
    # test suite when you only changed a comment.
    confidence_level = diagnosis_result.get("confidence", {}).get("level", "")
    if confidence_level == "High":
        return False

    return True


# ---------------------------------------------------------------------------
# Sequential Execution
# ---------------------------------------------------------------------------

def _run_agents_sequentially(
    diagnosis_result: Dict[str, Any],
    hypothesis: Dict[str, Any],
    agents: list,
    config: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Run agents one at a time, respecting max_agents and global timeout.

    Each agent is a callable with signature:
        (diagnosis_result: dict, hypothesis: dict) -> dict

    Error recovery:
    - If an agent raises an exception, we catch it and record an
      inconclusive verdict with ran=False.  The remaining agents
      still get their chance to run.
    - If the global timeout is exceeded, remaining agents are skipped
      entirely (not even attempted).

    WHY sequential?
    Simplicity.  Sequential execution is trivial to debug — you can read
    the run_log top-to-bottom and understand exactly what happened.
    Adding async/parallel execution later is a well-understood refactor.

    Args:
        diagnosis_result: The completed diagnosis dict (read-only).
        hypothesis:       The primary_hypothesis dict from the diagnosis.
        agents:           List of agent callables.
        config:           Orchestration config (max_agents, global_timeout_seconds).

    Returns:
        Tuple of (agents_run_list, run_log_list) where:
        - agents_run_list: List of normalized AgentVerdict dicts.
        - run_log_list:    List of metadata dicts for each agent attempt.
    """
    max_agents = config.get("max_agents", DEFAULT_CONFIG["max_agents"])
    global_timeout = config.get(
        "global_timeout_seconds", DEFAULT_CONFIG["global_timeout_seconds"]
    )

    # Use monotonic clock for timing — it's immune to system clock adjustments.
    # time.time() can jump forward/backward (NTP sync, DST, etc.), but
    # time.monotonic() always moves forward.  Critical for timeout logic.
    orchestration_start = time.monotonic()

    agents_run: List[Dict[str, Any]] = []
    run_log: List[Dict[str, Any]] = []

    for i, agent_callable in enumerate(agents):
        # --- Budget check: have we hit the max agents cap? ---
        if i >= max_agents:
            break

        # --- Timeout check: is there still time left? ---
        elapsed = time.monotonic() - orchestration_start
        if elapsed >= global_timeout:
            break

        # --- Run the agent with error recovery ---
        agent_started = time.monotonic()

        try:
            raw_result = agent_callable(diagnosis_result, hypothesis)
            # Normalize the raw result to ensure all required keys exist.
            # This is the boundary sanitization step — we don't trust agent
            # output to be well-formed, so we clean it before anyone else sees it.
            normalized = normalize_agent_verdict(raw_result)
        except Exception as exc:
            # Agent crashed.  Don't propagate the exception — record it as
            # inconclusive and move on.  This is the resilience guarantee:
            # one bad agent never takes down the whole orchestration.
            #
            # We extract the agent name from the callable if possible,
            # falling back to a generic name based on index position.
            agent_name = getattr(agent_callable, "__name__", f"agent_{i}")

            # Try to extract a more useful name from closure variables.
            # Our _fake_agent and _failing_agent factories create closures
            # where the agent_name is captured.  In production, agents will
            # have proper __name__ attributes.
            normalized = normalize_agent_verdict({
                "agent": agent_name,
                "ran": False,
                "verdict": "inconclusive",
                "reason": f"Agent crashed: {type(exc).__name__}: {exc}",
                "queries": [],
                "evidence": [],
                "cost": {"queries": 0, "seconds": 0.0},
            })

        agent_ended = time.monotonic()

        # Record in the run log for debugging/audit purposes.
        # This is the observability layer — like logging in a data pipeline
        # so you can reconstruct what happened after the fact.
        # Use relative offsets (seconds since orchestration started) instead
        # of absolute monotonic values.  Relative times are human-readable
        # (e.g., 0.0, 0.5, 1.2) and meaningful across machines/sessions.
        run_log.append({
            "agent": normalized["agent"],
            "started": agent_started - orchestration_start,
            "ended": agent_ended - orchestration_start,
            "verdict": normalized["verdict"],
        })

        agents_run.append(normalized)

    return agents_run, run_log


# ---------------------------------------------------------------------------
# Fusion Policy
# ---------------------------------------------------------------------------

def _fuse_verdicts(agents_run: List[Dict[str, Any]]) -> Tuple[str, str]:
    """Combine individual agent verdicts into a single fused verdict.

    Priority order (deterministic, highest wins):
        1. blocked         → Any agent says data is too broken to trust
        2. rejected        → Any agent disagrees with the diagnosis
        3. confirmed       → All non-abstaining agents agree
        4. inconclusive    → Treated as abstention (non-vote)

    WHY this ordering?
    - "blocked" is a hard stop — like a data quality check failing in a
      pipeline.  You can't trust downstream results if the data is bad.
    - "rejected" is a strong signal — one expert disagreeing is enough to
      warrant caution, even if others agree (conservative approach).
    - "inconclusive" is NOT a rejection — it just means the agent couldn't
      form an opinion (crashed, timed out, insufficient data).  We don't
      penalize the diagnosis for an agent that abstained.

    Args:
        agents_run: List of normalized AgentVerdict dicts.

    Returns:
        Tuple of (fused_verdict, fused_reason) where:
        - fused_verdict: One of "confirmed", "insufficient_evidence", "blocked".
        - fused_reason:  Human-readable summary explaining the fusion logic.
    """
    if not agents_run:
        return "insufficient_evidence", "No agents produced a verdict"

    # Collect all verdicts for analysis.
    verdicts = [a["verdict"] for a in agents_run]
    agent_names = [a["agent"] for a in agents_run]

    # --- Priority 1: blocked ---
    # Any single "blocked" verdict overrides everything else.
    if "blocked" in verdicts:
        blocked_agents = [
            agent_names[i] for i, v in enumerate(verdicts) if v == "blocked"
        ]
        return (
            "blocked",
            f"Blocked by: {', '.join(blocked_agents)}. "
            f"Data quality issues prevent reliable verification."
        )

    # --- Priority 2: rejected ---
    # Any single "rejected" verdict downgrades the overall result.
    # We map this to "insufficient_evidence" rather than "rejected" because
    # the orchestrator's job is triage, not final judgment.
    if "rejected" in verdicts:
        rejected_agents = [
            agent_names[i] for i, v in enumerate(verdicts) if v == "rejected"
        ]
        return (
            "insufficient_evidence",
            f"Rejected by: {', '.join(rejected_agents)}. "
            f"Diagnosis hypothesis not supported by all agents."
        )

    # --- Priority 3: confirmed ---
    # At least one agent confirmed AND no agents rejected/blocked.
    # Inconclusive agents are treated as abstentions — they don't block
    # confirmation.  This prevents flaky agents from holding up good diagnoses.
    if "confirmed" in verdicts:
        confirmed_agents = [
            agent_names[i] for i, v in enumerate(verdicts) if v == "confirmed"
        ]
        return (
            "confirmed",
            f"Confirmed by: {', '.join(confirmed_agents)}. "
            f"Diagnosis hypothesis verified."
        )

    # --- Priority 4: all inconclusive ---
    # If every agent abstained, we can't confirm anything.
    return (
        "insufficient_evidence",
        f"All agents returned inconclusive. "
        f"Unable to verify diagnosis hypothesis."
    )


def _verdict_to_decision_status(
    fused_verdict: str, original_status: str
) -> str:
    """Map a fused verdict to a decision_status value.

    This translates the orchestrator's conclusion into the same vocabulary
    that the rest of the system already understands (decision_status).

    Mapping:
    - "confirmed"             → keep the original status (diagnosis stands)
    - "blocked"               → "blocked_by_data_quality"
    - anything else           → "insufficient_evidence"

    WHY not just use the verdict directly?
    The decision_status field has its own vocabulary that downstream consumers
    (formatters, evaluators, CLI) already understand.  We translate into that
    vocabulary rather than forcing every consumer to learn a new set of terms.

    Args:
        fused_verdict:    The fused verdict from _fuse_verdicts().
        original_status:  The original decision_status from the diagnosis.

    Returns:
        The updated decision_status string.
    """
    if fused_verdict == "confirmed":
        # Diagnosis stands — keep whatever status it had.
        return original_status
    elif fused_verdict == "blocked":
        # Data quality issue — this maps directly to an existing status.
        return "blocked_by_data_quality"
    else:
        # Anything else (rejected, inconclusive, etc.) means we can't
        # confidently endorse the diagnosis.
        return "insufficient_evidence"


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------

def orchestrate(
    diagnosis_result: Dict[str, Any],
    agents: list,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run specialist agents against a completed diagnosis and fuse their verdicts.

    This is the main entry point for the multi-agent orchestrator.
    It is designed as a POST-PROCESS HOOK: call it after run_diagnosis()
    completes, pass in the diagnosis result, and get back a fused verdict.

    IMPORTANT: This function NEVER modifies the diagnosis_result dict.
    It only reads from it and returns a new dict.  The caller decides
    whether and how to merge the result.

    Typical usage:
        diagnosis = run_diagnosis(data)
        orch_result = orchestrate(diagnosis, [ranking_agent, dq_agent])
        diagnosis["orchestration"] = orch_result  # caller's choice to merge

    Args:
        diagnosis_result: The completed diagnosis dict from run_diagnosis().
                          Must contain: decision_status, confidence, primary_hypothesis.
        agents:           List of agent callables.  Each callable has signature:
                          (diagnosis_result: dict, hypothesis: dict) -> dict
        config:           Optional config overrides.  Keys:
                          - max_agents (int): Max agents to run.
                          - global_timeout_seconds (float): Wall-clock timeout.

    Returns:
        A dict conforming to the OrchestrationResult shape:
        - orchestrated:           bool — did orchestration actually run?
        - agents_run:             list — normalized AgentVerdict dicts
        - fused_verdict:          str  — the combined verdict
        - fused_reason:           str  — human-readable explanation
        - updated_decision_status: str  — new decision status after fusion
        - run_log:                list — per-agent metadata for debugging
    """
    # Merge config with defaults (caller overrides take precedence).
    effective_config = dict(DEFAULT_CONFIG)
    if config:
        effective_config.update(config)

    # --- Gate check: should we even run agents? ---
    if not _should_orchestrate(diagnosis_result, agents):
        # Build a skip reason that explains WHY we didn't run agents.
        # This is important for debugging: if a user asks "why didn't agents
        # run?", the reason field tells them without reading the code.
        decision_status = diagnosis_result.get("decision_status", "unknown")
        confidence_level = diagnosis_result.get("confidence", {}).get("level", "unknown")

        # Determine the appropriate fused_verdict for the skip scenario.
        # High confidence skips are optimistic (confirmed), others are not.
        if confidence_level == "High" and decision_status == "diagnosed":
            skip_verdict = "confirmed"
            skip_reason = (
                f"Skipped: High confidence diagnosis does not require "
                f"agent verification."
            )
        elif not agents:
            skip_verdict = "insufficient_evidence"
            skip_reason = "Skipped: No agents provided."
        else:
            skip_verdict = "insufficient_evidence"
            skip_reason = (
                f"Skipped: decision_status='{decision_status}' "
                f"(requires 'diagnosed')."
            )

        return {
            "orchestrated": False,
            "agents_run": [],
            "fused_verdict": skip_verdict,
            "fused_reason": skip_reason,
            "updated_decision_status": diagnosis_result.get(
                "decision_status", "unknown"
            ),
            "run_log": [],
        }

    # --- Extract the hypothesis for agents to verify ---
    hypothesis = diagnosis_result.get("primary_hypothesis", {})

    # --- Run agents sequentially ---
    agents_run_results, run_log = _run_agents_sequentially(
        diagnosis_result, hypothesis, agents, effective_config
    )

    # --- Fuse individual verdicts into one decision ---
    fused_verdict, fused_reason = _fuse_verdicts(agents_run_results)

    # --- Map fused verdict to a decision_status ---
    original_status = diagnosis_result.get("decision_status", "diagnosed")
    updated_status = _verdict_to_decision_status(fused_verdict, original_status)

    # --- Build the result (never mutates diagnosis_result) ---
    # Return full AgentVerdict dicts, not just names.  Downstream consumers
    # (Trace Viewer, formatters, logging) need per-agent evidence, reasoning,
    # and cost data — not just the agent's name.
    return {
        "orchestrated": True,
        "agents_run": agents_run_results,
        "fused_verdict": fused_verdict,
        "fused_reason": fused_reason,
        "updated_decision_status": updated_status,
        "run_log": run_log,
    }


# ---------------------------------------------------------------------------
# SearchMetricOrchestrator — Full 4-Stage Pipeline (v2 Architecture)
# ---------------------------------------------------------------------------
#
# WHY A CLASS INSTEAD OF A FUNCTION:
# The existing `orchestrate()` function is a stateless post-process hook.
# The new 4-stage pipeline (UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE)
# needs configuration (LLM callable, retry settings) and state that flows
# between stages (trace, understand_result passed to hypothesize, etc.).
# A class captures this naturally without threading config through every call.
#
# RELATIONSHIP TO orchestrate():
# SearchMetricOrchestrator does NOT replace orchestrate(). They serve
# different purposes:
# - orchestrate(): Post-process hook for agent verification (v1 architecture)
# - SearchMetricOrchestrator: Full investigation pipeline (v2 architecture)
# Both coexist in the same module — v1 callers are not affected.
# ---------------------------------------------------------------------------

from core.anomaly import check_data_quality, detect_step_change, match_co_movement_pattern
from core.decompose import run_decomposition
from core.diagnose import run_diagnosis
from contracts.seam_validator import validate_seam, SeamViolation
from trace.collector import InvestigationTrace
from trace.helpers import emit_deterministic_span
from harness.errors import OrchestratorError, StageError


class SearchMetricOrchestrator:
    """Full 4-stage pipeline: UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE.

    Each stage follows the same protocol:
    1. Validate input (pre-conditions)
    2. Execute stage logic (deterministic or LLM-based)
    3. Validate output with seam_validator (business rules)
    4. Emit trace span (record what was decided and why)

    The UNDERSTAND stage is fully deterministic (no LLM calls). It uses
    existing core tools (decompose, anomaly, diagnose) to produce a
    structured understanding of the metric movement.

    HYPOTHESIZE, DISPATCH, and SYNTHESIZE require an LLM callable and
    are not yet implemented (raise NotImplementedError).

    Usage:
        def my_llm(prompt, system, max_tokens):
            return "LLM response..."

        orch = SearchMetricOrchestrator(llm_callable=my_llm)
        report = orch.run(
            question="Click Quality dropped 6.2% WoW",
            rows=metric_rows,
            metric_field="click_quality_value",
            dimensions=["tenant_tier", "ai_enablement"],
        )

    Args:
        llm_callable: Function with signature (prompt, system, max_tokens) -> str.
            Used by HYPOTHESIZE, DISPATCH, and SYNTHESIZE stages.
            Not used by UNDERSTAND (deterministic).
        config: Optional dict with orchestration settings:
            - max_retries (int): Max LLM retries per stage (default: 2)
            - timeout_seconds (float): Per-stage timeout (default: 60)
    """

    # Default configuration — conservative settings for reliability
    DEFAULT_CONFIG: Dict[str, Any] = {
        "max_retries": 2,
        "timeout_seconds": 60,
    }

    def __init__(
        self,
        llm_callable: Any,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._llm = llm_callable
        self._config = dict(self.DEFAULT_CONFIG)
        if config:
            self._config.update(config)

    def run(
        self,
        question: str,
        rows: list,
        metric_field: str = "click_quality_value",
        dimensions: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Run the full 4-stage investigation pipeline.

        Currently only UNDERSTAND is implemented. The remaining stages
        raise NotImplementedError with descriptive messages explaining
        what they will do when implemented.

        Args:
            question: The investigation question (e.g., "Click Quality dropped 6.2% WoW").
            rows: List of metric row dicts. Must include a 'period' field
                  with values "baseline" or "current" to separate comparison periods.
            metric_field: Which metric column to analyze (default: click_quality_value).
            dimensions: List of dimension columns to decompose by.
                       Defaults to standard Enterprise Search dimensions.

        Returns:
            InvestigationReport dict with keys:
            - status: "completed" | "blocked" | "partial"
            - question: The original question
            - understand_result: Output from UNDERSTAND stage
            - trace: Full investigation trace as dict
            - (future) hypothesize_result, dispatch_result, synthesize_result

        Raises:
            StageError: If the UNDERSTAND stage fails due to seam validation.
            OrchestratorError: For unexpected pipeline failures.
        """
        # Create a fresh trace for this investigation
        trace = InvestigationTrace(question=question)

        # --- Stage 1: UNDERSTAND (deterministic, no LLM) ---
        try:
            understand_result = self._stage_understand(
                question=question,
                rows=rows,
                metric_field=metric_field,
                dimensions=dimensions,
                trace=trace,
            )
        except SeamViolation as e:
            # UNDERSTAND has a HARD gate — if seam validation fails,
            # the investigation cannot continue. Build a blocked report
            # explaining what went wrong and how to fix it.
            blocked_understand = {
                "question": question,
                "metric": metric_field,
                "data_quality_status": "fail",
                "metric_direction": "unknown",
                "severity": "blocked",
                "direction": "unknown",
                "step_change": None,
                "co_movement_pattern": {},
                "mix_shift_result": None,
                "data_quality_details": None,
            }
            return self._build_blocked_report(
                understand_result=blocked_understand,
                trace=trace,
                reason="; ".join(e.violations),
            )

        # Check if data quality failed — return blocked report
        # (this handles the case where check_data_quality returns "fail"
        # but the seam validator processes it as a violation)
        if understand_result.get("data_quality_status") == "fail":
            return self._build_blocked_report(
                understand_result=understand_result,
                trace=trace,
                reason=understand_result.get("data_quality_details", {}).get(
                    "reason", "Data quality check failed"
                ),
            )

        # --- Stages 2-4: Not yet implemented ---
        # These will be added in Tasks 9, 10, 11 respectively.
        # For now, return the UNDERSTAND result as a partial report.
        return {
            "status": "partial",
            "question": question,
            "stages_completed": ["UNDERSTAND"],
            "stages_remaining": ["HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"],
            "understand_result": understand_result,
            "trace": trace.to_dict(),
        }

    def _stage_understand(
        self,
        question: str,
        rows: list,
        metric_field: str,
        dimensions: Optional[list],
        trace: InvestigationTrace,
    ) -> Dict[str, Any]:
        """Stage 1: UNDERSTAND — deterministic analysis using core tools.

        This stage answers: "What happened?" using only code (no LLM).
        It runs the full diagnostic toolkit and produces a structured
        summary of the metric movement.

        Steps:
        1. Check data quality (gate check — can we trust this data?)
        2. Run decomposition (where is the movement concentrated?)
        3. Extract daily values for step-change detection
        4. Detect step change (overnight jump or gradual drift?)
        5. Match co-movement pattern (which known failure mode?)
        6. Run diagnosis (validate, build hypothesis, score confidence)
        7. Build UnderstandResult dict
        8. Validate with seam_validator (HARD gate — halts on failure)
        9. Emit trace span

        Args:
            question: Investigation question text.
            rows: Metric data rows (must have 'period' field).
            metric_field: Which metric to analyze.
            dimensions: Dimensions to decompose by.
            trace: InvestigationTrace to record decisions to.

        Returns:
            UnderstandResult dict conforming to the contract schema.

        Raises:
            SeamViolation: If UNDERSTAND seam validation fails (HARD gate).
        """
        # --- Step 1: Data quality gate ---
        # This is the most important check — if data is bad, everything
        # downstream is unreliable. Check FIRST, fail FAST.
        dq_result = check_data_quality(rows, trace=trace)

        # --- Step 2: Run decomposition ---
        # Even if data quality is "warn", we continue — the analyst
        # should see the decomposition alongside the warning.
        # If data quality is "fail", we still run decomposition to
        # populate the UnderstandResult, but the seam validator will
        # halt the pipeline at step 8.
        decomposition = run_decomposition(
            rows=rows,
            metric_field=metric_field,
            dimensions=dimensions,
            trace=trace,
        )

        # --- Step 3: Extract daily values for step-change detection ---
        # Step-change detection needs daily metric averages. We extract
        # these from the current-period rows (looking for overnight jumps
        # within the current period).
        daily_values = self._extract_daily_values(rows, metric_field)

        # --- Step 4: Detect step change ---
        step_change = detect_step_change(daily_values, trace=trace)

        # --- Step 5: Match co-movement pattern ---
        # Build the observed directions dict from the decomposition aggregate.
        # We need direction for each metric to match against the co-movement table.
        observed_directions = self._extract_observed_directions(rows, metric_field)
        co_movement = match_co_movement_pattern(observed_directions, trace=trace)

        # --- Step 6: Run diagnosis ---
        # Diagnosis consumes all prior analysis and produces the hypothesis.
        diagnosis = run_diagnosis(
            decomposition=decomposition,
            step_change_result=step_change,
            co_movement_result=co_movement,
            trust_gate_result=dq_result,
            trace=trace,
        )

        # --- Step 7: Build UnderstandResult ---
        # Extract key fields from diagnosis and decomposition into the
        # contract-defined UnderstandResult shape.
        aggregate = decomposition.get("aggregate", {})
        direction = aggregate.get("direction", "stable")
        severity = diagnosis.get("aggregate", aggregate).get("severity", "normal")

        understand_result: Dict[str, Any] = {
            "question": question,
            "metric": metric_field,
            "direction": direction,
            "severity": severity,
            "data_quality_status": dq_result.get("status", "pass"),
            "step_change": step_change if step_change.get("detected") else None,
            "co_movement_pattern": co_movement,
            "mix_shift_result": decomposition.get("mix_shift") or None,
            # IC9 Invisible Decision #1: metric_direction must be explicitly set
            "metric_direction": direction,
            "data_quality_details": dq_result,
            # Additional context for downstream stages
            "decomposition": decomposition,
            "diagnosis": diagnosis,
        }

        # --- Step 8: Seam validation (HARD gate) ---
        # UNDERSTAND uses a HARD gate — if validation fails, the pipeline
        # halts immediately. This prevents bad data from producing misleading
        # diagnoses. The SeamViolation exception propagates to run().
        validate_seam(
            result=understand_result,
            stage="UNDERSTAND",
            trace=trace,
        )

        # --- Step 9: Emit summary trace span ---
        # Record the overall UNDERSTAND outcome for downstream stages
        emit_deterministic_span(
            trace,
            tool="harness.orchestrator.SearchMetricOrchestrator._stage_understand",
            decision="understand_complete",
            value=f"{direction}_{severity}",
            human_summary=(
                f"UNDERSTAND complete: {metric_field} {direction} "
                f"(severity={severity}, dq={dq_result.get('status', 'unknown')})"
            ),
            agent_context=(
                f"metric={metric_field}, direction={direction}, severity={severity}, "
                f"dq_status={dq_result.get('status')}, "
                f"co_movement={co_movement.get('likely_cause', 'unknown')}, "
                f"step_change={step_change.get('detected', False)}"
            ),
        )

        return understand_result

    def _build_blocked_report(
        self,
        understand_result: Dict[str, Any],
        trace: InvestigationTrace,
        reason: str,
    ) -> Dict[str, Any]:
        """Build a report when the pipeline is halted (e.g., data quality failure).

        A blocked report explains WHY the investigation stopped and WHAT
        the user needs to fix before retrying. This is more useful than
        just raising an exception — the user gets actionable guidance.

        Args:
            understand_result: Partial UNDERSTAND output (may be incomplete).
            trace: The investigation trace (contains what we managed to record).
            reason: Human-readable explanation of why the pipeline was blocked.

        Returns:
            InvestigationReport dict with status="blocked".
        """
        # Emit a trace span recording the block decision
        emit_deterministic_span(
            trace,
            tool="harness.orchestrator.SearchMetricOrchestrator._build_blocked_report",
            decision="pipeline_blocked",
            value="blocked",
            human_summary=f"Pipeline blocked: {reason}",
            agent_context=f"blocked_reason={reason}",
        )

        return {
            "status": "blocked",
            "question": understand_result.get("question", ""),
            "stages_completed": [],
            "stages_remaining": ["UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"],
            "blocked_reason": reason,
            "understand_result": understand_result,
            "remediation": (
                "Fix the data quality issues described above, then rerun the investigation. "
                "Common fixes: verify data completeness > 96%, data freshness < 60 minutes, "
                "and ensure both baseline and current period data are present."
            ),
            "trace": trace.to_dict(),
        }

    def _stage_hypothesize(self, understand_result, trace):
        """Stage 2: HYPOTHESIZE — generate hypotheses using LLM.

        NOT YET IMPLEMENTED (Task 9).

        This stage will:
        1. Load corrections from corrections.yaml (past diagnostic mistakes)
        2. Build a prompt with UNDERSTAND context + domain knowledge
        3. Call the LLM to generate 3+ hypotheses with confirms_if criteria
        4. Validate with seam_validator (SOFT gate)
        5. Check co-movement consistency (Amendment 2)
        6. Check mix-shift consideration (Amendment 3)
        """
        raise NotImplementedError(
            "HYPOTHESIZE stage is not yet implemented (Task 9). "
            "This stage will use the LLM callable to generate hypotheses "
            "based on the UNDERSTAND result, domain knowledge, and past corrections."
        )

    def _stage_dispatch(self, hypothesize_result, understand_result, trace):
        """Stage 3: DISPATCH — investigate hypotheses using specialist agents.

        NOT YET IMPLEMENTED (Task 10).

        This stage will:
        1. Route each hypothesis to the appropriate specialist agent
        2. Agents gather evidence (connector checks, timeline analysis, etc.)
        3. Each agent returns findings with raw data evidence
        4. Validate with seam_validator (SOFT gate)
        5. Check narrative-data coherence
        """
        raise NotImplementedError(
            "DISPATCH stage is not yet implemented (Task 10). "
            "This stage will dispatch hypotheses to specialist agents "
            "for evidence gathering and return structured findings."
        )

    def _stage_synthesize(self, dispatch_result, understand_result, trace):
        """Stage 4: SYNTHESIZE — produce the final investigation report.

        NOT YET IMPLEMENTED (Task 11).

        This stage will:
        1. Build a prompt with all prior stage context (token-budgeted)
        2. Call the LLM to produce a structured report (7 mandatory sections)
        3. Validate with seam_validator (RETRY gate — retry once, then soft)
        4. Check effect-size proportionality for P0 severity
        5. Require upgrade_condition statement
        6. Add self-evaluation confidence score
        """
        raise NotImplementedError(
            "SYNTHESIZE stage is not yet implemented (Task 11). "
            "This stage will use the LLM callable to produce a final "
            "investigation report with 7 mandatory sections and confidence grading."
        )

    # --- Helper methods ---

    def _extract_daily_values(
        self, rows: list, metric_field: str
    ) -> List[float]:
        """Extract daily metric averages from rows for step-change detection.

        Groups rows by date (from metric_ts or date field) and computes
        the daily mean for the target metric. Returns a chronologically
        sorted list of daily averages.

        If no date field is found, returns an empty list (step-change
        detection will report "not detected" for < 2 values).
        """
        from collections import defaultdict

        daily_buckets: Dict[str, List[float]] = defaultdict(list)

        for row in rows:
            # Try common date field names
            ts = row.get("metric_ts", row.get("date", row.get("event_ts", "")))
            if not ts:
                continue
            # Extract date portion (first 10 chars of ISO timestamp)
            date_str = str(ts)[:10] if ts else "unknown"
            try:
                val = float(row.get(metric_field, 0))
            except (ValueError, TypeError):
                val = 0.0
            daily_buckets[date_str].append(val)

        if not daily_buckets:
            return []

        # Sort by date and compute daily averages
        sorted_dates = sorted(daily_buckets.keys())
        return [
            sum(daily_buckets[d]) / len(daily_buckets[d])
            for d in sorted_dates
        ]

    def _extract_observed_directions(
        self, rows: list, primary_metric: str
    ) -> Dict[str, str]:
        """Extract observed metric directions for co-movement pattern matching.

        Compares baseline vs current period means for each metric and
        classifies the direction as "up", "down", or "stable".

        The co-movement table expects directions for:
        - click_quality, search_quality_success, ai_trigger, ai_success

        Uses a 1% relative threshold to distinguish "stable" from real movement.
        """
        from core.schema import normalize_metric_name

        # Metrics to check for co-movement (maps output key → row field name)
        metric_fields = {
            "click_quality": "click_quality_value",
            "search_quality_success": "search_quality_success_value",
            "ai_trigger": "ai_trigger",
            "ai_success": "ai_success",
        }

        # Split by period
        baseline_rows = [r for r in rows if r.get("period") == "baseline"]
        current_rows = [r for r in rows if r.get("period") == "current"]

        if not baseline_rows or not current_rows:
            # Can't compute directions without both periods
            return {}

        directions: Dict[str, str] = {}
        # Threshold for "stable" — less than 1% relative change
        STABLE_THRESHOLD = 0.01

        for key, field in metric_fields.items():
            # Compute means for each period
            bl_vals = []
            cur_vals = []
            for r in baseline_rows:
                try:
                    bl_vals.append(float(r.get(field, 0)))
                except (ValueError, TypeError):
                    pass
            for r in current_rows:
                try:
                    cur_vals.append(float(r.get(field, 0)))
                except (ValueError, TypeError):
                    pass

            if not bl_vals or not cur_vals:
                directions[key] = "stable"
                continue

            bl_mean = sum(bl_vals) / len(bl_vals)
            cur_mean = sum(cur_vals) / len(cur_vals)

            if bl_mean == 0:
                directions[key] = "stable"
                continue

            relative_change = (cur_mean - bl_mean) / abs(bl_mean)

            if relative_change > STABLE_THRESHOLD:
                directions[key] = "up"
            elif relative_change < -STABLE_THRESHOLD:
                directions[key] = "down"
            else:
                directions[key] = "stable"

        return directions
