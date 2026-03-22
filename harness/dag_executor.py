"""DAG executor — parallel hypothesis dispatch with error isolation and circuit breaker.

WHY THIS EXISTS:
The current pipeline investigates hypotheses sequentially — 3 hypotheses at 40s each = 120s.
DAGExecutor runs them in parallel using ThreadPoolExecutor, cutting DISPATCH latency to ~50s.
This only activates in Complex mode; Medium mode stays sequential.

DESIGN DECISION: ThreadPoolExecutor, not asyncio.
The entire codebase is synchronous. ConnectorInvestigator already uses ThreadPoolExecutor.
Converting to asyncio would require changing the LLM callable signature, all stage methods,
and test patterns — massive scope creep for marginal benefit when parallelizing 3-5 calls.

ERROR MODEL:
- Per-hypothesis isolation: one failure → "inconclusive" finding, others continue
- Circuit breaker: 3+ failures in same execution → StageError raised
- Per-agent timeout: separate from global pipeline timeout
- Coverage check: every hypothesis should have at least one finding

ANALOGY: Like a MapReduce shuffle — each hypothesis is an independent map task.
If one mapper crashes, the job continues with partial results. Only if too many
mappers fail does the entire stage abort.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Any, Callable, Dict, List, Optional

from harness.errors import StageError
from harness.phoenix_tracer import dual_emit, PHOENIX_AVAILABLE

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_CONFIG = {
    "max_workers": 5,          # Max parallel threads (5 is plenty for 3-5 LLM calls)
    "per_agent_timeout": 60,   # Seconds per hypothesis investigation
    "circuit_breaker_threshold": 3,  # Failures before aborting
}


# =============================================================================
# DAGExecutor
# =============================================================================

class DAGExecutor:
    """Execute hypothesis investigations in parallel with error isolation.

    Usage:
        executor = DAGExecutor(investigate_fn=my_investigate_function)
        results = executor.execute(hypotheses, context)
        # results.findings = list of SubAgentFinding dicts
        # results.failed_count = number of failed investigations
        # results.circuit_broken = True if circuit breaker tripped

    Args:
        investigate_fn: Callable with signature:
            (hypothesis: dict, context: dict) -> dict (SubAgentFinding)
            This is the function that investigates a single hypothesis.
            For the orchestrator, this wraps _dispatch_via_llm or _dispatch_via_agents.
        config: Optional config overrides (max_workers, per_agent_timeout, etc.)
    """

    def __init__(
        self,
        investigate_fn: Callable,
        config: Optional[Dict[str, Any]] = None,
    ):
        self._investigate = investigate_fn
        self._config = dict(DEFAULT_CONFIG)
        if config:
            self._config.update(config)

    def execute(
        self,
        hypotheses: List[Dict[str, Any]],
        context: Dict[str, Any],
        trace=None,
    ) -> Dict[str, Any]:
        """Execute hypothesis investigations in parallel.

        Steps:
        1. Submit all hypotheses to ThreadPoolExecutor
        2. Collect results as they complete (as_completed for earliest-first)
        3. Wrap failures in inconclusive findings (error isolation)
        4. Check circuit breaker (3+ failures → abort)
        5. Run coverage check (every hypothesis should have a finding)
        6. Return aggregated results

        Args:
            hypotheses: List of hypothesis dicts to investigate.
            context: Shared context dict (understand_result, hypothesize_context, etc.)
            trace: Optional InvestigationTrace for recording execution metadata.

        Returns:
            Dict with keys:
            - findings: List of SubAgentFinding dicts
            - failed_count: Number of failed investigations
            - circuit_broken: Whether circuit breaker tripped
            - execution_log: Per-hypothesis timing and status

        Raises:
            StageError: If circuit breaker threshold is reached.
        """
        if not hypotheses:
            return {
                "findings": [],
                "failed_count": 0,
                "circuit_broken": False,
                "execution_log": [],
            }

        max_workers = self._config["max_workers"]
        per_timeout = self._config["per_agent_timeout"]
        cb_threshold = self._config["circuit_breaker_threshold"]

        findings: List[Dict[str, Any]] = []
        execution_log: List[Dict[str, Any]] = []
        failure_count = 0
        circuit_broken = False

        start_time = time.monotonic()

        # --- Capture OTel context for thread propagation ---
        # WHY: ThreadPoolExecutor workers run in separate threads that don't
        # inherit the parent thread's OTel context. Without explicit propagation,
        # LLM calls inside workers would create orphan spans (not nested under
        # the DISPATCH stage span). We capture the context here and attach it
        # in each worker callable.
        otel_context = None
        if PHOENIX_AVAILABLE:
            try:
                from opentelemetry import context as otel_ctx
                otel_context = otel_ctx.get_current()
            except Exception:
                pass  # OTel errors must never crash the pipeline

        def _investigate_with_context(hyp, ctx):
            """Wrapper that attaches OTel context before running investigation."""
            token = None
            if otel_context is not None:
                try:
                    from opentelemetry import context as otel_ctx
                    token = otel_ctx.attach(otel_context)
                except Exception:
                    pass  # OTel errors must never crash the pipeline
            try:
                return self._investigate(hyp, ctx)
            finally:
                if token is not None:
                    try:
                        from opentelemetry import context as otel_ctx
                        otel_ctx.detach(token)
                    except Exception:
                        pass

        # --- Submit all hypotheses to the thread pool ---
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # Map future → hypothesis AND submit timestamp for result attribution.
            # Fix #1: record submitted_at when future is created, not when collected,
            # so execution_log.duration reflects actual wall-clock investigation time.
            future_to_hyp: Dict[Future, Dict[str, Any]] = {}
            future_submitted_at: Dict[Future, float] = {}

            for hyp in hypotheses:
                future = pool.submit(_investigate_with_context, hyp, context)
                future_to_hyp[future] = hyp
                future_submitted_at[future] = time.monotonic()

            # --- Collect results as they complete ---
            # Fix #2: as_completed() called without timeout — per-future
            # timeout is handled by future.result(timeout=per_timeout) below.
            # Error isolation wraps each failure as an inconclusive finding.
            for future in as_completed(future_to_hyp):
                hyp = future_to_hyp[future]
                hyp_id = hyp.get("hypothesis_id", "unknown")
                submitted_at = future_submitted_at[future]

                try:
                    finding = future.result(timeout=per_timeout)
                    completed_at = time.monotonic()
                    findings.append(finding)
                    execution_log.append({
                        "hypothesis_id": hyp_id,
                        "status": "success",
                        "duration": completed_at - submitted_at,
                    })

                except Exception as exc:
                    # --- Error isolation: wrap failure as inconclusive ---
                    completed_at = time.monotonic()
                    failure_count += 1
                    findings.append({
                        "agent_name": "dag_executor",
                        "hypothesis_id": hyp_id,
                        "verdict": "inconclusive",
                        "confidence": 0.0,
                        "evidence": [],
                        "narrative": f"Investigation failed: {type(exc).__name__}: {str(exc)[:200]}",
                        "adjacent_observations": [],
                    })
                    execution_log.append({
                        "hypothesis_id": hyp_id,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {str(exc)[:100]}",
                        "duration": completed_at - submitted_at,
                    })

                    logger.warning(
                        "Hypothesis %s investigation failed: %s",
                        hyp_id, str(exc)[:200],
                    )

                    # --- Circuit breaker check ---
                    if failure_count >= cb_threshold:
                        circuit_broken = True
                        logger.error(
                            "Circuit breaker tripped: %d/%d failures (threshold=%d)",
                            failure_count, len(hypotheses), cb_threshold,
                        )
                        # Fix #5: cancel() only prevents NOT-YET-STARTED tasks from
                        # running. It cannot interrupt already-running threads. This
                        # stops the pool from starting more work, but threads already
                        # in flight will finish naturally when the `with` block exits.
                        for f in future_to_hyp:
                            f.cancel()
                        break

        total_duration = time.monotonic() - start_time

        # --- Coverage backfill: create inconclusive findings for unprocessed hypotheses ---
        # When the circuit breaker fires or the loop exits early, some hypotheses
        # may never have had .result() called. Downstream stages (SYNTHESIZE)
        # expect every hypothesis to have a finding — a silent gap would cause
        # missing coverage in the final report.
        hyp_ids_with_findings = {f.get("hypothesis_id") for f in findings}
        all_hyp_ids = {h.get("hypothesis_id") for h in hypotheses}
        missing_coverage = all_hyp_ids - hyp_ids_with_findings

        # Don't increment failure_count for backfills — these hypotheses
        # never ran, so they didn't "fail." failure_count should only reflect
        # investigations that were attempted and crashed. Conflating the two
        # would mislead SYNTHESIZE into thinking more agents crashed than
        # actually did (e.g., "5/5 failed" when only 1 crashed and 4 were skipped).
        for hyp in hypotheses:
            hyp_id = hyp.get("hypothesis_id", "unknown")
            if hyp_id in missing_coverage:
                findings.append({
                    "agent_name": "dag_executor",
                    "hypothesis_id": hyp_id,
                    "verdict": "inconclusive",
                    "confidence": 0.0,
                    "evidence": [],
                    "narrative": "Investigation not started — circuit breaker tripped before this hypothesis was processed",
                    "adjacent_observations": [],
                })

        # --- Emit trace span ---
        dual_emit(
            trace,
            tool="harness.dag_executor.DAGExecutor.execute",
            decision="parallel_dispatch",
            value=f"{'circuit_broken' if circuit_broken else 'completed'}",
            stage="DISPATCH",
            human_summary=(
                f"Parallel dispatch: {len(findings)} findings from "
                f"{len(hypotheses)} hypotheses in {total_duration:.1f}s. "
                f"Failures: {failure_count}. "
                f"{'CIRCUIT BREAKER TRIPPED.' if circuit_broken else ''}"
            ),
            agent_context=(
                f"total={len(hypotheses)}, success={len(hypotheses) - failure_count}, "
                f"failed={failure_count}, circuit_broken={circuit_broken}, "
                f"duration={total_duration:.1f}s, "
                f"missing_coverage={sorted(missing_coverage) if missing_coverage else 'none'}"
            ),
            swimlane="deterministic",
        )

        result = {
            "findings": findings,
            "failed_count": failure_count,
            "circuit_broken": circuit_broken,
            "execution_log": execution_log,
        }

        # --- Raise StageError if circuit breaker tripped ---
        if circuit_broken:
            raise StageError(
                message=(
                    f"DISPATCH circuit breaker: {failure_count}/{len(hypotheses)} "
                    f"hypothesis investigations failed (threshold={cb_threshold}). "
                    f"Partial findings ({len(findings) - failure_count} successful) available."
                ),
                stage="DISPATCH",
                violations=[
                    f"Circuit breaker tripped: {failure_count} failures exceeded threshold {cb_threshold}"
                ],
                details=result,
            )

        return result
