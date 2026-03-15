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
