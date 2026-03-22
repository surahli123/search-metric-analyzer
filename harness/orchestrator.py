"""SearchMetricOrchestrator — 5-stage investigation pipeline.

ARCHITECTURE:
The orchestrator coordinates the 5-stage pipeline:
    QUESTION_PARSE -> UNDERSTAND -> HYPOTHESIZE -> DISPATCH -> SYNTHESIZE

Each stage is implemented as a standalone function in harness/stages/:
- stage_understand: deterministic analysis (no LLM)
- stage_hypothesize: LLM generates hypotheses
- stage_dispatch / stage_dispatch_parallel: investigate hypotheses
- stage_synthesize: produce final report

The orchestrator class handles:
- Pipeline coordination (calling stages in order)
- Mode selection (Simple/Medium/Complex)
- Error handling (blocked reports, stage failures)
- Configuration (LLM callable, timeouts, retry settings)

WHY A CLASS:
The pipeline needs configuration (LLM callable, retry settings) and
coordination logic (mode selection, error handling) that's shared
across invocations. A class captures this naturally.

HISTORY:
- v1: orchestrate() function (post-process hook for agent verification)
  -> DELETED in this refactor. Tests in test_agent_orchestrator.py removed.
- v2: SearchMetricOrchestrator class with run_v2() entry point
  -> run_v2() renamed to run() in this refactor.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from contracts.seam_validator import SeamViolation, validate_seam
from harness.errors import OrchestratorError, StageError
from harness.stages import (
    stage_understand,
    stage_hypothesize,
    stage_dispatch,
    stage_dispatch_parallel,
    stage_synthesize,
)
from trace.collector import InvestigationTrace
from harness.phoenix_tracer import register_phoenix, stage_span, flush, dual_emit


class SearchMetricOrchestrator:
    """5-stage investigation pipeline with mode selection.

    Pipeline: QUESTION_PARSE -> UNDERSTAND -> HYPOTHESIZE -> DISPATCH -> SYNTHESIZE

    Three modes:
    - Simple: knowledge lookup only, skips the 4-stage pipeline
    - Medium: sequential 4-stage pipeline
    - Complex: parallel DISPATCH via DAGExecutor, otherwise same as Medium

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
            Not used by UNDERSTAND (deterministic) or Simple mode.
        config: Optional dict with orchestration settings:
            - max_retries (int): Max LLM retries per stage (default: 2)
            - timeout_seconds (float): Per-stage timeout (default: 60)
            - agents (list): Agent callables for DISPATCH (optional)
            - max_dispatch_workers (int): Parallel dispatch workers (default: 5)
            - circuit_breaker_threshold (int): Max failures before halt (default: 3)
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
        override_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the agent-aware investigation pipeline.

        This is the main entry point. It:
        1. Parses the question into a structured brief
        2. Selects mode (Simple/Medium/Complex) based on the brief
        3. Routes to the appropriate execution path

        Args:
            question: The investigation question text.
            rows: List of metric row dicts with 'period' field.
            metric_field: Which metric column to analyze.
            dimensions: Dimension columns for decomposition.
            override_mode: Optional mode override ("simple", "medium", "complex").

        Returns:
            InvestigationReport dict with keys:
            - status: "complete" | "blocked"
            - question: The original question
            - question_brief: Parsed question brief
            - mode_decision: Mode selection decision with confidence
            - mode: Selected mode string
            - stages_completed: List of completed stage names
            - understand_result: Output from UNDERSTAND stage (Medium/Complex)
            - hypothesize_result: Output from HYPOTHESIZE stage (Medium/Complex)
            - dispatch_result: Output from DISPATCH stage (Medium/Complex)
            - synthesis: Output from SYNTHESIZE stage (Medium/Complex)
            - trace: Full investigation trace as dict
        """
        from harness.question_parser import parse_question
        from harness.mode_selector import select_mode

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

        question_type = question_brief.get("question_type")

        # --- Simple mode: direct knowledge lookup, no pipeline ---
        if mode == "simple":
            dual_emit(
                trace,
                tool="harness.orchestrator.SearchMetricOrchestrator.run",
                decision="mode_execution",
                value="simple_direct",
                stage="QUESTION_PARSE",
                human_summary="Simple mode: direct knowledge lookup, skipping pipeline",
                agent_context=f"mode=simple, question_type={question_brief.get('question_type')}",
                swimlane="deterministic",
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

        # --- Medium/Complex mode: run the shared 4-stage pipeline ---
        pipeline_result = self._run_pipeline(
            question=question,
            rows=rows,
            metric_field=metric_field,
            dimensions=dimensions,
            mode=mode,
            trace=trace,
            question_type=question_type,
        )

        # Augment with mode selection fields
        pipeline_result["question_brief"] = question_brief
        pipeline_result["mode_decision"] = mode_decision
        pipeline_result["mode"] = mode
        if "stages_completed" in pipeline_result and pipeline_result["stages_completed"]:
            pipeline_result["stages_completed"].insert(0, "QUESTION_PARSE")

        return pipeline_result

    # Keep run_v2 as an alias during transition to avoid breaking any
    # callers that haven't been updated yet. Can be removed in v3.
    run_v2 = run

    def run_pipeline_only(
        self,
        question: str,
        rows: list,
        metric_field: str = "click_quality_value",
        dimensions: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Run the 4-stage pipeline directly (skipping QUESTION_PARSE and mode selection).

        Always uses "medium" mode (sequential dispatch). This is the
        legacy entry point — new callers should use run() instead.

        Args:
            question: The investigation question.
            rows: Metric data rows (must have 'period' field).
            metric_field: Which metric column to analyze.
            dimensions: Dimension columns for decomposition.

        Returns:
            InvestigationReport dict (same shape as run() for Medium mode,
            but without question_brief and mode_decision fields).
        """
        trace = InvestigationTrace(question=question)
        return self._run_pipeline(
            question=question,
            rows=rows,
            metric_field=metric_field,
            dimensions=dimensions,
            mode="medium",
            trace=trace,
        )

    def _run_pipeline(
        self,
        question: str,
        rows: list,
        metric_field: str,
        dimensions: Optional[list],
        mode: str,
        trace: InvestigationTrace,
        question_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Shared 4-stage pipeline: UNDERSTAND -> HYPOTHESIZE -> DISPATCH -> SYNTHESIZE.

        The mode parameter controls whether DISPATCH is parallel (complex)
        or sequential (medium).

        Args:
            question: Investigation question text.
            rows: Metric data rows.
            metric_field: Which metric column to analyze.
            dimensions: Dimension columns for decomposition.
            mode: "medium" (sequential dispatch) or "complex" (parallel dispatch).
            trace: InvestigationTrace for this investigation.
            question_type: Optional question type for seam validation rules.

        Returns:
            InvestigationReport dict.

        Raises:
            StageError: If a pipeline stage fails.
        """
        # --- Phoenix observability: register tracer (idempotent) ---
        # WHY here and not in __init__: register_phoenix() sets up OTel
        # globally, which should happen lazily when the pipeline actually
        # runs, not when the orchestrator is just instantiated.
        phoenix_provider = register_phoenix()

        try:
            # --- Stage 1: UNDERSTAND (deterministic, no LLM) ---
            with stage_span("UNDERSTAND", mode=mode):
                try:
                    understand_result = stage_understand(
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
                    return self._build_blocked_report(
                        understand_result=blocked_understand, trace=trace,
                        reason="; ".join(e.violations),
                    )

            if understand_result.get("data_quality_status") == "fail":
                return self._build_blocked_report(
                    understand_result=understand_result, trace=trace,
                    reason=understand_result.get("data_quality_details", {}).get(
                        "reason", "Data quality check failed"),
                )

            # --- Stage 2: HYPOTHESIZE (LLM-based) ---
            with stage_span("HYPOTHESIZE", mode=mode):
                hypothesize_result = stage_hypothesize(
                    understand_result=understand_result,
                    trace=trace,
                    llm_callable=self._llm,
                )

            # --- Stage 3: DISPATCH ---
            # Complex mode: parallel dispatch via DAGExecutor
            # Medium mode: sequential dispatch
            with stage_span("DISPATCH", mode=mode):
                if mode == "complex":
                    dispatch_result = stage_dispatch_parallel(
                        hypothesis_set=hypothesize_result,
                        understand_result=understand_result,
                        trace=trace,
                        llm_callable=self._llm,
                        config=self._config,
                        question_type=question_type,
                    )
                else:
                    dispatch_result = stage_dispatch(
                        hypothesis_set=hypothesize_result,
                        understand_result=understand_result,
                        trace=trace,
                        llm_callable=self._llm,
                        config=self._config,
                        question_type=question_type,
                    )

            # --- Stage 4: SYNTHESIZE (LLM-based, RETRY(1) then SOFT gate) ---
            with stage_span("SYNTHESIZE", mode=mode):
                synthesis_result = stage_synthesize(
                    dispatch_result=dispatch_result,
                    understand_result=understand_result,
                    hypothesize_result=hypothesize_result,
                    trace=trace,
                    llm_callable=self._llm,
                    mode=mode,
                )

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
        finally:
            # Always flush OTel spans, even if the pipeline raised an exception.
            # WHY in finally: ensures spans are sent to Phoenix for debugging
            # failed investigations too — not just successful ones.
            flush(phoenix_provider)

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
        dual_emit(
            trace,
            tool="harness.orchestrator.SearchMetricOrchestrator._build_blocked_report",
            decision="pipeline_blocked",
            value="blocked",
            human_summary=f"Pipeline blocked: {reason}",
            agent_context=f"blocked_reason={reason}",
            swimlane="deterministic",
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
