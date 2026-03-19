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
from core.corrections import load_corrections, find_relevant_corrections
from core.decompose import run_decomposition
from core.diagnose import run_diagnosis
from contracts.seam_validator import validate_seam, SeamViolation
from harness.errors import OrchestratorError, StageError, LLMParseError, LLMAPIError
from harness.llm import extract_json
from trace.collector import InvestigationTrace
from trace.helpers import emit_deterministic_span


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

        Executes: UNDERSTAND → HYPOTHESIZE → DISPATCH → SYNTHESIZE.
        Each stage validates its output via seam_validator before proceeding.

        Args:
            question: The investigation question (e.g., "Click Quality dropped 6.2% WoW").
            rows: List of metric row dicts. Must include a 'period' field
                  with values "baseline" or "current" to separate comparison periods.
            metric_field: Which metric column to analyze (default: click_quality_value).
            dimensions: List of dimension columns to decompose by.
                       Defaults to standard Enterprise Search dimensions.

        Returns:
            InvestigationReport dict with keys:
            - status: "complete" | "blocked"
            - question: The original question
            - stages_completed: List of completed stage names
            - understand_result: Output from UNDERSTAND stage
            - hypothesize_result: Output from HYPOTHESIZE stage
            - dispatch_result: Output from DISPATCH stage (FindingSet)
            - synthesis: Output from SYNTHESIZE stage (SynthesisReport)
            - trace: Full investigation trace as dict

        Raises:
            StageError: If a stage fails (e.g., seam validation, JSON parse).
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

        # --- Stage 2: HYPOTHESIZE (LLM-based) ---
        try:
            hypothesize_result = self._stage_hypothesize(
                understand_result=understand_result,
                trace=trace,
            )
        except StageError:
            # HYPOTHESIZE StageError (e.g., JSON parse failure) — the
            # investigation can't continue without hypotheses.
            # Let it propagate to the caller.
            raise

        # --- Stage 3: DISPATCH (LLM or agent-based) ---
        try:
            dispatch_result = self._stage_dispatch(
                hypothesis_set=hypothesize_result,
                understand_result=understand_result,
                trace=trace,
            )
        except StageError:
            # DISPATCH StageError (e.g., all hypotheses failed) — propagate.
            # The caller can inspect stage="DISPATCH" to know what broke.
            raise

        # --- Stage 4: SYNTHESIZE (LLM-based, RETRY(1) then SOFT gate) ---
        synthesis_result = self._stage_synthesize(
            dispatch_result=dispatch_result,
            understand_result=understand_result,
            hypothesize_result=hypothesize_result,
            trace=trace,
        )

        # --- All 4 stages completed — return full investigation report ---
        return {
            "status": "complete",
            "question": question,
            "stages_completed": ["UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"],
            "understand_result": understand_result,
            "hypothesize_result": hypothesize_result,
            "dispatch_result": dispatch_result,
            "synthesis": synthesis_result,
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

    def _stage_hypothesize(
        self,
        understand_result: Dict[str, Any],
        trace: InvestigationTrace,
    ) -> Dict[str, Any]:
        """Stage 2: HYPOTHESIZE — LLM generates hypotheses from UNDERSTAND results.

        Returns a HypothesisSet dict conforming to contracts/hypothesize.py schema.

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
            understand_result: Output from _stage_understand().
            trace: InvestigationTrace to record decisions to.

        Returns:
            HypothesisSet dict with keys: hypotheses, exclusions, investigation_context.

        Raises:
            StageError: If JSON extraction from LLM response fails.
            LLMAPIError: If LLM call fails with a transient error (propagates).
        """
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
        system_prompt = self._build_hypothesize_system_prompt()
        user_prompt = self._build_hypothesize_user_prompt(
            understand_result=understand_result,
            corrections=relevant_corrections,
            trace=trace,
        )

        # --- Step 3: Call the LLM ---
        # LLMAPIError (transient) will propagate up — the caller
        # (or _call_with_retry if used) handles retry logic.
        raw_response = self._llm(user_prompt, system_prompt, 2000)

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
        hypothesis_set = self._normalize_hypothesis_set(parsed)

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

        # Use trace.emit() directly for LLM-generated spans (not deterministic)
        # because emit_deterministic_span() sets code_enforced=True, which would
        # be misleading for an LLM decision.
        from trace.span import TraceSpan
        trace.emit(TraceSpan(
            stage="HYPOTHESIZE",
            swimlane="llm_generated",
            tool="harness.orchestrator.SearchMetricOrchestrator._stage_hypothesize",
            decision="hypothesis_inclusion",
            code_enforced=False,
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
        ))

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
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "HYPOTHESIZE seam validation failed (SOFT gate — continuing): %s",
                "; ".join(validation["violations"]),
            )

        # --- Step 7: Return the HypothesisSet ---
        return hypothesis_set

    def _build_hypothesize_system_prompt(self) -> str:
        """Build the system prompt for HYPOTHESIZE stage.

        Delegates to harness.prompts for the actual prompt content.
        Kept as a method for backward compatibility with existing tests.
        """
        from harness.prompts import build_hypothesize_system_prompt
        return build_hypothesize_system_prompt()

    def _build_hypothesize_user_prompt(
        self,
        understand_result: Dict[str, Any],
        corrections: List[Dict[str, Any]],
        trace: InvestigationTrace,
    ) -> str:
        """Build the user prompt for HYPOTHESIZE stage.

        Delegates to harness.prompts for the actual prompt content.
        """
        from harness.prompts import build_hypothesize_user_prompt
        understand_context = trace.agent_context_for("UNDERSTAND")
        return build_hypothesize_user_prompt(
            understand_result=understand_result,
            corrections=corrections,
            understand_context=understand_context,
        )

    def _normalize_hypothesis_set(self, parsed: Any) -> Dict[str, Any]:
        """Normalize parsed LLM output into a valid HypothesisSet dict.

        Delegates to harness.prompts for the actual normalization.
        """
        from harness.prompts import normalize_hypothesis_set
        return normalize_hypothesis_set(parsed)

    def _stage_dispatch(self, hypothesis_set, understand_result, trace):
        """Stage 3: DISPATCH — investigate hypotheses using specialist agents.

        Routes each hypothesis to either:
        - Agent callables (if config["agents"] is provided)
        - LLM callable (default — one call per hypothesis)

        Per-hypothesis error isolation: individual failures produce an
        inconclusive finding (NOT a pipeline halt). Only raises StageError
        if the hypothesis set is empty OR all hypotheses fail.

        Steps:
        1. Validate hypothesis set is non-empty
        2. For each hypothesis: investigate via agent or LLM
        3. Collect findings with per-hypothesis error isolation
        4. Emit IC9 Invisible Decision #3 trace span (context_construction)
        5. Validate with seam_validator (SOFT gate)
        6. Return FindingSet dict

        Args:
            hypothesis_set: Output from _stage_hypothesize() (HypothesisSet dict).
            understand_result: Output from _stage_understand().
            trace: InvestigationTrace to record decisions to.

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
        agents = self._config.get("agents")

        for hyp in hypotheses:
            hyp_id = hyp.get("hypothesis_id", "unknown")

            try:
                if agents:
                    # --- Agent callable path ---
                    # Run each agent on this hypothesis, take the first result
                    finding = self._dispatch_via_agents(
                        agents=agents,
                        diagnosis_context=diagnosis_context,
                        hypothesis=hyp,
                    )
                else:
                    # --- LLM path ---
                    finding = self._dispatch_via_llm(
                        hypothesis=hyp,
                        understand_result=understand_result,
                        hypothesize_context=hypothesize_context,
                    )

                findings.append(finding)
                context_construction_log.append(
                    f"Hypothesis {hyp_id}: investigated successfully"
                )

            except Exception as e:
                # Per-hypothesis error isolation: failures → inconclusive finding.
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
        from trace.span import TraceSpan
        trace.emit(TraceSpan(
            stage="DISPATCH",
            swimlane="llm_generated",
            tool="harness.orchestrator.SearchMetricOrchestrator._stage_dispatch",
            decision="context_construction",
            code_enforced=False,
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
        ))

        # --- Seam validation (SOFT gate) ---
        # DISPATCH uses a SOFT gate — if one finding has no evidence,
        # we log it but don't halt. One bad finding shouldn't kill
        # an otherwise useful investigation.
        validation = validate_seam(
            result=finding_set,
            stage="DISPATCH",
            trace=trace,
        )

        if not validation["passed"]:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "DISPATCH seam validation failed (SOFT gate — continuing): %s",
                "; ".join(validation["violations"]),
            )

        return finding_set

    def _dispatch_via_agents(self, agents, diagnosis_context, hypothesis):
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

                # Convert AgentVerdict → SubAgentFinding.
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
            except Exception:
                # Agent failed — try the next one
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

    def _dispatch_via_llm(self, hypothesis, understand_result, hypothesize_context):
        """Investigate a single hypothesis using the LLM callable.

        Builds a per-hypothesis prompt, calls the LLM, and parses the
        response into a SubAgentFinding dict.
        """
        hyp_id = hypothesis.get("hypothesis_id", "unknown")

        system_prompt = self._build_dispatch_system_prompt()
        user_prompt = self._build_dispatch_user_prompt(
            hypothesis=hypothesis,
            understand_result=understand_result,
            hypothesize_context=hypothesize_context,
        )

        raw_response = self._llm(user_prompt, system_prompt, 1500)

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

    def _build_dispatch_system_prompt(self) -> str:
        """Delegates to harness.prompts."""
        from harness.prompts import build_dispatch_system_prompt
        return build_dispatch_system_prompt()

    def _build_dispatch_user_prompt(self, hypothesis, understand_result, hypothesize_context):
        """Delegates to harness.prompts."""
        from harness.prompts import build_dispatch_user_prompt
        return build_dispatch_user_prompt(
            hypothesis=hypothesis,
            understand_result=understand_result,
            hypothesize_context=hypothesize_context,
        )

    def _stage_synthesize(self, dispatch_result, understand_result,
                          hypothesize_result, trace):
        """Stage 4: SYNTHESIZE — produce the final investigation report.

        Builds a prompt from all prior stages, calls the LLM, and validates
        the report against the SynthesisReport contract.

        Uses RETRY(1) then SOFT gate:
        - First attempt: validate with seam_validator
        - If fails: retry once with violations appended to prompt
        - If second attempt also fails: continue with completeness_warnings
          (expensive investigation work is NOT discarded)

        Steps:
        1. Build system + user prompt with all stage context
        2. Call the LLM to produce a structured report
        3. Validate with seam_validator (RETRY gate)
        4. If validation fails, retry with violation feedback
        5. If retry also fails, degrade gracefully with warnings
        6. Emit IC9 Invisible Decision #4 trace span (narrative_selection)
        7. Return SynthesisReport dict

        Args:
            dispatch_result: Output from _stage_dispatch() (FindingSet dict).
            understand_result: Output from _stage_understand().
            hypothesize_result: Output from _stage_hypothesize().
            trace: InvestigationTrace to record decisions to.

        Returns:
            SynthesisReport dict with 7 mandatory sections + metadata.

        Raises:
            StageError: If JSON extraction from LLM response fails on both attempts.
        """
        system_prompt = self._build_synthesize_system_prompt()
        user_prompt = self._build_synthesize_user_prompt(
            understand_result=understand_result,
            hypothesize_result=hypothesize_result,
            dispatch_result=dispatch_result,
            trace=trace,
        )

        # --- First attempt ---
        raw_response = self._llm(user_prompt, system_prompt, 3000)

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
        report = self._normalize_synthesis_report(report, trace)

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
            )
        except SeamViolation as first_violation:
            # First attempt failed — retry with violation feedback
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "SYNTHESIZE first attempt failed validation — retrying: %s",
                "; ".join(first_violation.violations),
            )

            # Build retry prompt with violations appended
            retry_prompt = self._build_synthesize_retry_prompt(
                original_prompt=user_prompt,
                violations=first_violation.violations,
            )

            # --- Second attempt (retry) ---
            raw_response_2 = self._llm(retry_prompt, system_prompt, 3000)

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
                self._emit_synthesize_trace(report, trace)
                return report

            report = self._normalize_synthesis_report(report, trace)

            # Validate the retry result
            try:
                validation = validate_seam(
                    result=report,
                    stage="SYNTHESIZE",
                    trace=trace,
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
        self._emit_synthesize_trace(report, trace)

        return report

    def _normalize_synthesis_report(self, parsed, trace):
        """Delegates to harness.prompts."""
        from harness.prompts import normalize_synthesis_report
        return normalize_synthesis_report(parsed, trace.trace_id)

    def _emit_synthesize_trace(self, report, trace):
        """Emit IC9 Invisible Decision #4: narrative_selection.

        Records what narrative framing the LLM chose for the report.
        Previously invisible — you saw the report but not why the LLM
        chose that particular confidence grade, severity, or framing.
        """
        from trace.span import TraceSpan
        trace.emit(TraceSpan(
            stage="SYNTHESIZE",
            swimlane="llm_generated",
            tool="harness.orchestrator.SearchMetricOrchestrator._stage_synthesize",
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

    def _build_synthesize_system_prompt(self) -> str:
        """Delegates to harness.prompts."""
        from harness.prompts import build_synthesize_system_prompt
        return build_synthesize_system_prompt()

    def _build_synthesize_user_prompt(self, understand_result, hypothesize_result,
                                       dispatch_result, trace):
        """Delegates to harness.prompts."""
        from harness.prompts import build_synthesize_user_prompt
        dispatch_context = trace.agent_context_for("DISPATCH", max_tokens=1500)
        return build_synthesize_user_prompt(
            understand_result=understand_result,
            hypothesize_result=hypothesize_result,
            dispatch_result=dispatch_result,
            dispatch_context=dispatch_context,
        )

    def _build_synthesize_retry_prompt(self, original_prompt, violations):
        """Delegates to harness.prompts."""
        from harness.prompts import build_synthesize_retry_prompt
        return build_synthesize_retry_prompt(original_prompt, violations)

    # --- Parallel dispatch (Complex mode) ---

    def _stage_dispatch_parallel(
        self,
        hypothesis_set: Dict[str, Any],
        understand_result: Dict[str, Any],
        trace,
    ) -> Dict[str, Any]:
        """Stage 3 (Complex mode): Parallel hypothesis investigation via DAGExecutor.

        Uses ThreadPoolExecutor to investigate hypotheses concurrently.
        Each hypothesis gets its own thread with error isolation —
        one failure produces an inconclusive finding, not a pipeline halt.

        Circuit breaker: if 3+ hypotheses fail, raises StageError with
        partial findings available in the error details.
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

        # The investigate function wraps _dispatch_via_llm for each hypothesis
        def investigate_hypothesis(hyp, ctx):
            return self._dispatch_via_llm(
                hypothesis=hyp,
                understand_result=ctx["understand_result"],
                hypothesize_context=ctx["hypothesize_context"],
            )

        executor = DAGExecutor(
            investigate_fn=investigate_hypothesis,
            config={
                "max_workers": self._config.get("max_dispatch_workers", 5),
                "per_agent_timeout": self._config.get("timeout_seconds", 60),
                "circuit_breaker_threshold": self._config.get("circuit_breaker_threshold", 3),
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
        validation = validate_seam(
            result=finding_set,
            stage="DISPATCH",
            trace=trace,
        )

        if not validation["passed"]:
            logger = __import__("logging").getLogger(__name__)
            logger.warning(
                "DISPATCH seam validation failed (SOFT gate — continuing): %s",
                "; ".join(validation["violations"]),
            )

        return finding_set

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

    # -------------------------------------------------------------------
    # run_v2() — Wave 5 agent-aware pipeline
    # -------------------------------------------------------------------

    def run_v2(
        self,
        question: str,
        rows: list,
        metric_field: str = "click_quality_value",
        dimensions: Optional[list] = None,
        override_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the agent-aware investigation pipeline (Wave 5).

        This extends run() with:
        1. Question parsing — classifies question into structured brief
        2. Mode selection — routes to Simple/Medium/Complex based on brief
        3. Registry-aware execution — agents loaded from agents/ directory
        4. Mode-appropriate dispatch — parallel for Complex (via DAGExecutor, PR C)

        Backward compatibility: run() is unchanged. run_v2() adds the new
        QUESTION_PARSE stage and mode-aware routing on top. If mode selection
        picks Medium, the pipeline behaves identically to run().

        Args:
            question: The investigation question text.
            rows: List of metric row dicts with 'period' field.
            metric_field: Which metric column to analyze.
            dimensions: Dimension columns for decomposition.
            override_mode: Optional mode override ("simple", "medium", "complex").

        Returns:
            InvestigationReport dict with additional keys:
            - question_brief: Parsed question brief
            - mode_decision: Mode selection decision with confidence
            All existing run() fields are preserved for Medium/Complex modes.
        """
        from harness.question_parser import parse_question
        from harness.mode_selector import select_mode
        from contracts.seam_validator import validate_seam, SeamViolation

        # Create trace for this investigation
        trace = InvestigationTrace(question=question)

        # --- Stage 0: QUESTION_PARSE (deterministic, no LLM) ---
        question_brief = parse_question(question, trace=trace)

        # Validate the question brief (HARD gate)
        try:
            validate_seam(
                result=question_brief,
                stage="QUESTION_PARSE",
                trace=trace,
            )
        except SeamViolation as e:
            return {
                "status": "blocked",
                "question": question,
                "blocked_reason": f"Question parse failed: {'; '.join(e.violations)}",
                "question_brief": question_brief,
                "trace": trace.to_dict(),
            }

        # --- Mode selection ---
        mode_decision = select_mode(
            question_brief=question_brief,
            override_mode=override_mode,
            trace=trace,
        )
        mode = mode_decision["mode"]

        # --- Simple mode: direct knowledge lookup, no pipeline ---
        if mode == "simple":
            emit_deterministic_span(
                trace,
                tool="harness.orchestrator.SearchMetricOrchestrator.run_v2",
                decision="mode_execution",
                value="simple_direct",
                stage="QUESTION_PARSE",
                human_summary="Simple mode: direct knowledge lookup, skipping pipeline",
                agent_context=f"mode=simple, question_type={question_brief.get('question_type')}",
            )
            return {
                "status": "complete",
                "question": question,
                "mode": "simple",
                "question_brief": question_brief,
                "mode_decision": mode_decision,
                "stages_completed": ["QUESTION_PARSE"],
                "trace": trace.to_dict(),
                # Simple mode has no pipeline output — caller handles lookup
            }

        # --- Medium/Complex mode: run the full 4-stage pipeline ---
        # Reuse existing run() logic via internal stage methods.
        # The only difference for Complex mode is in DISPATCH (PR C adds
        # parallel execution via DAGExecutor).

        # Stage 1: UNDERSTAND
        try:
            understand_result = self._stage_understand(
                question=question,
                rows=rows,
                metric_field=metric_field,
                dimensions=dimensions,
                trace=trace,
            )
        except SeamViolation as e:
            blocked_understand = {
                "question": question, "metric": metric_field,
                "data_quality_status": "fail", "metric_direction": "unknown",
                "severity": "blocked", "direction": "unknown",
                "step_change": None, "co_movement_pattern": {},
                "mix_shift_result": None, "data_quality_details": None,
            }
            report = self._build_blocked_report(
                understand_result=blocked_understand, trace=trace,
                reason="; ".join(e.violations),
            )
            report["question_brief"] = question_brief
            report["mode_decision"] = mode_decision
            return report

        if understand_result.get("data_quality_status") == "fail":
            report = self._build_blocked_report(
                understand_result=understand_result, trace=trace,
                reason=understand_result.get("data_quality_details", {}).get(
                    "reason", "Data quality check failed"),
            )
            report["question_brief"] = question_brief
            report["mode_decision"] = mode_decision
            return report

        # Stage 2: HYPOTHESIZE
        try:
            hypothesize_result = self._stage_hypothesize(
                understand_result=understand_result, trace=trace,
            )
        except StageError:
            raise

        # Stage 3: DISPATCH
        # Complex mode: parallel dispatch via DAGExecutor
        # Medium mode: sequential dispatch via existing _stage_dispatch
        if mode == "complex":
            try:
                dispatch_result = self._stage_dispatch_parallel(
                    hypothesis_set=hypothesize_result,
                    understand_result=understand_result,
                    trace=trace,
                )
            except StageError:
                raise
        else:
            try:
                dispatch_result = self._stage_dispatch(
                    hypothesis_set=hypothesize_result,
                    understand_result=understand_result,
                    trace=trace,
                )
            except StageError:
                raise

        # Stage 4: SYNTHESIZE
        synthesis_result = self._stage_synthesize(
            dispatch_result=dispatch_result,
            understand_result=understand_result,
            hypothesize_result=hypothesize_result,
            trace=trace,
        )

        return {
            "status": "complete",
            "question": question,
            "mode": mode,
            "question_brief": question_brief,
            "mode_decision": mode_decision,
            "stages_completed": [
                "QUESTION_PARSE", "UNDERSTAND", "HYPOTHESIZE",
                "DISPATCH", "SYNTHESIZE",
            ],
            "understand_result": understand_result,
            "hypothesize_result": hypothesize_result,
            "dispatch_result": dispatch_result,
            "synthesis": synthesis_result,
            "trace": trace.to_dict(),
        }
