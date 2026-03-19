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
from trace.helpers import emit_deterministic_span

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

        # --- Submit all hypotheses to the thread pool ---
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            # Map future → hypothesis for result attribution
            future_to_hyp: Dict[Future, Dict[str, Any]] = {}

            for hyp in hypotheses:
                future = pool.submit(self._investigate, hyp, context)
                future_to_hyp[future] = hyp

            # --- Collect results as they complete ---
            for future in as_completed(future_to_hyp, timeout=per_timeout * len(hypotheses)):
                hyp = future_to_hyp[future]
                hyp_id = hyp.get("hypothesis_id", "unknown")
                agent_start = time.monotonic()

                try:
                    finding = future.result(timeout=per_timeout)
                    findings.append(finding)
                    execution_log.append({
                        "hypothesis_id": hyp_id,
                        "status": "success",
                        "duration": time.monotonic() - agent_start,
                    })

                except Exception as exc:
                    # --- Error isolation: wrap failure as inconclusive ---
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
                        "duration": time.monotonic() - agent_start,
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
                        # Cancel remaining futures
                        for f in future_to_hyp:
                            f.cancel()
                        break

        total_duration = time.monotonic() - start_time

        # --- Coverage check: warn if any hypotheses have no findings ---
        hyp_ids_with_findings = {f.get("hypothesis_id") for f in findings}
        all_hyp_ids = {h.get("hypothesis_id") for h in hypotheses}
        missing_coverage = all_hyp_ids - hyp_ids_with_findings

        # --- Emit trace span ---
        if trace is not None:
            emit_deterministic_span(
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
