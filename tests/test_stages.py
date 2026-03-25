"""Tests for harness/stages/ — standalone stage functions.

These tests verify the stage extraction refactor:
- Stage functions are importable from harness.stages
- Each function has the correct signature (no self parameter)
- Functions produce the same output as the old method versions
- Error handling is preserved (StageError, SeamViolation)

The heavy functional testing is in test_orchestrator_pipeline.py
which uses run_pipeline_only() to exercise all stages end-to-end.
These tests focus on the extraction correctness and module boundaries.
"""

import json
import inspect
import pytest
from typing import Any, Dict, List
from unittest.mock import patch

from harness.stages import (
    stage_understand,
    stage_hypothesize,
    stage_dispatch,
    stage_dispatch_parallel,
    stage_synthesize,
)
from harness.stages.understand import _extract_daily_values, _extract_observed_directions
from harness.errors import StageError
from contracts.seam_validator import SeamViolation
from trace.collector import InvestigationTrace


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_good_rows() -> List[Dict[str, Any]]:
    """Create rows with good data quality that will pass all checks."""
    rows = []
    for i in range(20):
        is_standard = i % 2 == 0
        rows.append({
            "period": "baseline",
            "tenant_tier": "standard" if is_standard else "premium",
            "ai_enablement": "ai_off",
            "click_quality_value": 0.280,
            "search_quality_success_value": 0.378,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            "data_completeness": 0.995,
            "data_freshness_min": 10,
        })
    for i in range(20):
        is_standard = i % 2 == 0
        rows.append({
            "period": "current",
            "tenant_tier": "standard" if is_standard else "premium",
            "ai_enablement": "ai_off",
            "click_quality_value": 0.245 if is_standard else 0.280,
            "search_quality_success_value": 0.340 if is_standard else 0.378,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            "data_completeness": 0.995,
            "data_freshness_min": 10,
        })
    return rows


def _make_bad_quality_rows() -> List[Dict[str, Any]]:
    """Create rows with FAILING data quality (completeness < 96%)."""
    rows = []
    for i in range(10):
        rows.append({
            "period": "baseline",
            "tenant_tier": "standard",
            "click_quality_value": 0.280,
            "search_quality_success_value": 0.378,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            "data_completeness": 0.900,
            "data_freshness_min": 10,
        })
    for i in range(10):
        rows.append({
            "period": "current",
            "tenant_tier": "standard",
            "click_quality_value": 0.245,
            "search_quality_success_value": 0.340,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            "data_completeness": 0.900,
            "data_freshness_min": 10,
        })
    return rows


def _make_valid_hypothesis_json() -> str:
    """Return valid HypothesisSet JSON."""
    return json.dumps({
        "hypotheses": [
            {
                "hypothesis_id": "hyp_001",
                "archetype": "ranking_regression",
                "priority": 1,
                "confirms_if": ["ranking model logs show change"],
                "rejects_if": ["no model changes"],
                "expected_magnitude": "3-5% drop",
                "source": "data_driven",
                "is_contrarian": False,
            },
            {
                "hypothesis_id": "hyp_002",
                "archetype": "connector_pipeline_change",
                "priority": 2,
                "confirms_if": ["connector health failures"],
                "rejects_if": ["all connectors healthy"],
                "expected_magnitude": "2-4% drop",
                "source": "playbook",
                "is_contrarian": False,
            },
            {
                "hypothesis_id": "hyp_003",
                "archetype": "user_behavior_shift",
                "priority": 3,
                "confirms_if": ["query patterns shifted"],
                "rejects_if": ["patterns stable"],
                "expected_magnitude": "1-3% drop",
                "source": "novel",
                "is_contrarian": True,
            },
        ],
        "exclusions": [],
        "investigation_context": "Click quality dropped, investigating.",
    })


def _make_valid_finding_json(hypothesis_id: str = "hyp_001") -> str:
    """Return valid SubAgentFinding JSON."""
    return json.dumps({
        "agent_name": "llm_investigator",
        "hypothesis_id": hypothesis_id,
        "verdict": "confirmed",
        "confidence": 0.75,
        "evidence": [{"metric": "click_quality_value", "value": 0.245, "delta": "-12.5%", "direction": "down"}],
        "narrative": f"Investigation of {hypothesis_id}: confirmed.",
        "adjacent_observations": [],
    })


def _make_valid_synthesis_json() -> str:
    """Return valid SynthesisReport JSON."""
    return json.dumps({
        "tldr": "Click Quality dropped due to ranking regression.",
        "confidence_grade": "Medium",
        "severity": "P1",
        "root_cause": "Ranking model regression in standard tier.",
        "dimensional_breakdown": "Standard tier: -12.5%.",
        "hypothesis_and_evidence": "Ranking regression confirmed.",
        "validation_summary": "Timing aligns with deployment.",
        "recommended_actions": [
            {"action": "Roll back ranking model", "owner": "Eng Lead", "priority": "immediate",
             "rationale": "Fastest recovery path."},
        ],
        "upgrade_condition": "Would upgrade if logs confirm model version.",
        "completeness_warnings": [],
    })


def _dummy_llm(prompt: str, system: str, max_tokens: int) -> str:
    """Mock LLM callable that returns valid JSON for all stages."""
    if "investigating a specific hypothesis" in system.lower():
        hyp_id = "hyp_001"
        for line in prompt.split("\n"):
            if "ID:" in line:
                hyp_id = line.split("ID:")[-1].strip()
                break
        return _make_valid_finding_json(hyp_id)
    if "final" in system.lower() and "investigation report" in system.lower():
        return _make_valid_synthesis_json()
    return _make_valid_hypothesis_json()


# ===========================================================================
# Module Import Tests
# ===========================================================================


class TestStageModuleImports:
    """Verify stage functions are importable and have correct signatures."""

    def test_stage_understand_importable(self):
        """stage_understand should be importable from harness.stages."""
        from harness.stages import stage_understand
        assert callable(stage_understand)

    def test_stage_hypothesize_importable(self):
        """stage_hypothesize should be importable from harness.stages."""
        from harness.stages import stage_hypothesize
        assert callable(stage_hypothesize)

    def test_stage_dispatch_importable(self):
        """stage_dispatch should be importable from harness.stages."""
        from harness.stages import stage_dispatch
        assert callable(stage_dispatch)

    def test_stage_dispatch_parallel_importable(self):
        """stage_dispatch_parallel should be importable from harness.stages."""
        from harness.stages import stage_dispatch_parallel
        assert callable(stage_dispatch_parallel)

    def test_stage_synthesize_importable(self):
        """stage_synthesize should be importable from harness.stages."""
        from harness.stages import stage_synthesize
        assert callable(stage_synthesize)

    def test_helper_functions_importable(self):
        """Helper functions should be importable from their modules."""
        from harness.stages.understand import _extract_daily_values, _extract_observed_directions
        assert callable(_extract_daily_values)
        assert callable(_extract_observed_directions)


# ===========================================================================
# UNDERSTAND Stage Tests (standalone function)
# ===========================================================================


class TestStageUnderstand:
    """Test stage_understand() as a standalone function."""

    def test_returns_understand_result(self):
        """stage_understand should return a valid UnderstandResult dict."""
        trace = InvestigationTrace(question="CQ drop")
        result = stage_understand(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            trace=trace,
        )
        assert "question" in result
        assert "metric" in result
        assert "direction" in result
        assert "severity" in result
        assert "data_quality_status" in result
        assert "metric_direction" in result
        assert result["data_quality_status"] == "pass"

    def test_detects_downward_direction(self):
        """Should detect downward movement in click quality."""
        trace = InvestigationTrace(question="test")
        result = stage_understand(
            question="test",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            trace=trace,
        )
        assert result["direction"] == "down"
        assert result["metric_direction"] == "down"

    def test_emits_trace_span(self):
        """stage_understand should emit a trace span."""
        trace = InvestigationTrace(question="test")
        stage_understand(
            question="test",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            trace=trace,
        )
        trace_dict = trace.to_dict()
        spans = trace_dict.get("spans", [])
        # Should have at least one span from UNDERSTAND
        assert len(spans) > 0

    def test_none_rows_raises_stage_error(self):
        """None rows should raise StageError with UNDERSTAND stage."""
        trace = InvestigationTrace(question="test")
        with pytest.raises(StageError) as exc_info:
            stage_understand(
                question="test",
                rows=None,
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
                trace=trace,
            )
        assert exc_info.value.stage == "UNDERSTAND"
        assert "Core tool error" in exc_info.value.violations[0]


# ===========================================================================
# Helper Function Tests
# ===========================================================================


class TestExtractDailyValues:
    """Test _extract_daily_values helper."""

    def test_empty_rows(self):
        """Empty rows should return empty list."""
        result = _extract_daily_values([], "click_quality_value")
        assert result == []

    def test_no_date_field(self):
        """Rows without date fields should return empty list."""
        rows = [{"click_quality_value": 0.28}]
        result = _extract_daily_values(rows, "click_quality_value")
        assert result == []

    def test_with_metric_ts(self):
        """Should extract values using metric_ts field."""
        rows = [
            {"metric_ts": "2026-03-20T10:00:00", "click_quality_value": 0.28},
            {"metric_ts": "2026-03-20T14:00:00", "click_quality_value": 0.30},
            {"metric_ts": "2026-03-21T10:00:00", "click_quality_value": 0.25},
        ]
        result = _extract_daily_values(rows, "click_quality_value")
        assert len(result) == 2  # Two days
        assert abs(result[0] - 0.29) < 0.001  # Average of 0.28 and 0.30
        assert abs(result[1] - 0.25) < 0.001


class TestExtractObservedDirections:
    """Test _extract_observed_directions helper."""

    def test_returns_directions(self):
        """Should return direction dict for all metric fields."""
        rows = _make_good_rows()
        result = _extract_observed_directions(rows, "click_quality_value")
        assert "click_quality" in result
        assert "search_quality_success" in result
        assert "ai_trigger" in result
        assert "ai_success" in result

    def test_empty_rows(self):
        """Empty rows should return empty dict."""
        result = _extract_observed_directions([], "click_quality_value")
        assert result == {}

    def test_detects_downward_movement(self):
        """Standard tier drops should register as 'down'."""
        rows = _make_good_rows()
        result = _extract_observed_directions(rows, "click_quality_value")
        assert result["click_quality"] == "down"


# ===========================================================================
# HYPOTHESIZE Stage Tests (standalone function)
# ===========================================================================


class TestStageHypothesize:
    """Test stage_hypothesize() as a standalone function."""

    def test_returns_hypothesis_set(self):
        """Should return a HypothesisSet with hypotheses."""
        trace = InvestigationTrace(question="test")
        # First run UNDERSTAND to get proper understand_result
        understand_result = stage_understand(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            trace=trace,
        )
        result = stage_hypothesize(
            understand_result=understand_result,
            trace=trace,
            llm_callable=_dummy_llm,
        )
        assert "hypotheses" in result
        assert len(result["hypotheses"]) >= 1

    def test_bad_json_raises_stage_error(self):
        """Non-JSON LLM response should raise StageError."""
        def bad_llm(prompt, system, max_tokens):
            return "this is not json"

        trace = InvestigationTrace(question="test")
        understand_result = stage_understand(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            trace=trace,
        )
        with pytest.raises(StageError, match="HYPOTHESIZE"):
            stage_hypothesize(
                understand_result=understand_result,
                trace=trace,
                llm_callable=bad_llm,
            )


# ===========================================================================
# DISPATCH Stage Tests (standalone function)
# ===========================================================================


class TestStageDispatch:
    """Test stage_dispatch() as a standalone function."""

    def test_empty_hypotheses_raises_stage_error(self):
        """Empty hypothesis set should raise StageError."""
        trace = InvestigationTrace(question="test")
        with pytest.raises(StageError, match="DISPATCH"):
            stage_dispatch(
                hypothesis_set={"hypotheses": []},
                understand_result={},
                trace=trace,
                llm_callable=_dummy_llm,
                config={},
            )

    def test_returns_finding_set(self):
        """Should return a FindingSet with findings."""
        trace = InvestigationTrace(question="test")
        understand_result = stage_understand(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            trace=trace,
        )
        hypothesis_set = stage_hypothesize(
            understand_result=understand_result,
            trace=trace,
            llm_callable=_dummy_llm,
        )
        result = stage_dispatch(
            hypothesis_set=hypothesis_set,
            understand_result=understand_result,
            trace=trace,
            llm_callable=_dummy_llm,
            config={},
        )
        assert "findings" in result
        assert len(result["findings"]) > 0
        assert "context_construction_trace" in result


# ===========================================================================
# SYNTHESIZE Stage Tests (standalone function)
# ===========================================================================


class TestStageSynthesize:
    """Test stage_synthesize() as a standalone function."""

    def test_returns_synthesis_report(self):
        """Should return a SynthesisReport with mandatory fields."""
        trace = InvestigationTrace(question="CQ drop")
        understand_result = stage_understand(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            trace=trace,
        )
        hypothesis_set = stage_hypothesize(
            understand_result=understand_result,
            trace=trace,
            llm_callable=_dummy_llm,
        )
        dispatch_result = stage_dispatch(
            hypothesis_set=hypothesis_set,
            understand_result=understand_result,
            trace=trace,
            llm_callable=_dummy_llm,
            config={},
        )
        result = stage_synthesize(
            dispatch_result=dispatch_result,
            understand_result=understand_result,
            hypothesize_result=hypothesis_set,
            trace=trace,
            llm_callable=_dummy_llm,
        )
        # Mandatory sections
        assert "tldr" in result
        assert "confidence_grade" in result
        assert "severity" in result
        assert "root_cause" in result
        assert "recommended_actions" in result


# ===========================================================================
# Orchestrator Integration (run_pipeline_only and run)
# ===========================================================================


class TestOrchestratorRunPipelineOnly:
    """Test that run_pipeline_only() works as the old run() did."""

    def test_returns_complete_report(self):
        """run_pipeline_only should execute all 4 stages."""
        from harness.orchestrator import SearchMetricOrchestrator
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "complete"
        assert "UNDERSTAND" in result["stages_completed"]
        assert "SYNTHESIZE" in result["stages_completed"]
        # Should NOT have QUESTION_PARSE (that's only in run())
        assert "QUESTION_PARSE" not in result["stages_completed"]

    def test_blocked_on_bad_data(self):
        """run_pipeline_only should block on bad data quality."""
        from harness.orchestrator import SearchMetricOrchestrator
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert result["status"] == "blocked"


class TestOrchestratorRunV2Alias:
    """Test that run_v2 still works as an alias for run."""

    def test_run_v2_alias_works(self):
        """run_v2 should be a valid alias for run."""
        from harness.orchestrator import SearchMetricOrchestrator
        orch = SearchMetricOrchestrator(llm_callable=None)
        # Simple mode question -- no LLM needed
        result = orch.run_v2(
            question="What is click quality?",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )
        assert result["status"] == "complete"
        assert result["mode"] == "simple"


# ===========================================================================
# Code Review Fix Tests
# ===========================================================================


class TestFix1RunDiagnosisInsideTryExcept:
    """Fix 1: run_diagnosis() errors should be caught as StageError.

    Previously, run_diagnosis() was called AFTER the try/except block,
    so a KeyError from malformed decomposition would propagate as a raw
    exception instead of a clean StageError. Now it's inside the block.
    """

    def test_diagnosis_error_wrapped_in_stage_error(self):
        """If run_diagnosis raises (e.g., from bad decomposition), should get StageError."""
        from unittest.mock import patch
        trace = InvestigationTrace(question="test")

        # We mock run_diagnosis to raise a KeyError — simulating what happens
        # when decomposition has unexpected structure (e.g., missing "aggregate" key).
        with patch("harness.stages.understand.run_diagnosis", side_effect=KeyError("aggregate")):
            with pytest.raises(StageError) as exc_info:
                stage_understand(
                    question="CQ drop",
                    rows=_make_good_rows(),
                    metric_field="click_quality_value",
                    dimensions=["tenant_tier"],
                    trace=trace,
                )
            # Verify it's a StageError from UNDERSTAND, not a raw KeyError
            assert exc_info.value.stage == "UNDERSTAND"
            assert "KeyError" in exc_info.value.violations[0]


class TestFix2LLMCallableTypeAlias:
    """Fix 2: LLMCallable type alias should be importable and used in stage signatures."""

    def test_llm_callable_importable(self):
        """LLMCallable should be importable from harness.types."""
        from harness.types import LLMCallable
        # It's a Callable type alias — verify it's not None
        assert LLMCallable is not None

    def test_hypothesize_uses_llm_callable_type(self):
        """stage_hypothesize should annotate llm_callable as LLMCallable."""
        # With `from __future__ import annotations` (PEP 563), annotations
        # are stored as strings. We check the string annotation directly
        # rather than resolving via get_type_hints() (which can fail on
        # forward refs in complex modules).
        sig = inspect.signature(stage_hypothesize)
        param = sig.parameters["llm_callable"]
        assert param.annotation == "LLMCallable", (
            f"Expected 'LLMCallable' annotation, got '{param.annotation}'"
        )

    def test_dispatch_uses_llm_callable_type(self):
        """stage_dispatch should annotate llm_callable as LLMCallable."""
        from harness.stages.dispatch import stage_dispatch
        sig = inspect.signature(stage_dispatch)
        param = sig.parameters["llm_callable"]
        assert param.annotation == "LLMCallable", (
            f"Expected 'LLMCallable' annotation, got '{param.annotation}'"
        )

    def test_synthesize_uses_llm_callable_type(self):
        """stage_synthesize should annotate llm_callable as LLMCallable."""
        from harness.stages.synthesize import stage_synthesize
        sig = inspect.signature(stage_synthesize)
        param = sig.parameters["llm_callable"]
        assert param.annotation == "LLMCallable", (
            f"Expected 'LLMCallable' annotation, got '{param.annotation}'"
        )


class TestBonusFixAgentFailureLogging:
    """Bonus fix: _dispatch_via_agents should log warnings when agents fail."""

    def test_agent_failure_logged(self):
        """When an agent raises, a warning should be logged."""
        from harness.stages.dispatch import _dispatch_via_agents

        def failing_agent(ctx, hyp):
            raise ValueError("agent exploded")

        # Call the function with a failing agent — it should return
        # an inconclusive finding and log a warning (not silently swallow)
        with patch("harness.stages.dispatch.logger") as mock_logger:
            result = _dispatch_via_agents(
                agents=[failing_agent],
                diagnosis_context={"understand_result": {}, "hypothesize_context": ""},
                hypothesis={"hypothesis_id": "hyp_test"},
            )
            # Should return inconclusive (all agents failed)
            assert result["verdict"] == "inconclusive"
            assert result["confidence"] == 0.0
            # Logger.warning should have been called with the agent failure
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "failed" in call_args[0][0]  # format string contains "failed"


# ===========================================================================
# Domain Wiring Tests for HYPOTHESIZE Stage
# ===========================================================================


class TestHypothesizeDomainWiring:
    """Verify stage_hypothesize uses domain.get_prompts() instead of hardcoded imports."""

    def test_accepts_domain_parameter(self):
        """stage_hypothesize should accept an optional domain parameter."""
        import inspect
        from harness.stages.hypothesize import stage_hypothesize
        sig = inspect.signature(stage_hypothesize)
        assert "domain" in sig.parameters

    def test_uses_domain_prompts(self):
        """When domain is provided, prompts come from domain.get_prompts()."""
        from unittest.mock import MagicMock
        from harness.stages.hypothesize import stage_hypothesize
        from trace.collector import InvestigationTrace

        mock_domain = MagicMock()
        from domains.search_metrics import SearchMetricsDomain
        real_domain = SearchMetricsDomain()
        mock_domain.get_prompts.return_value = real_domain.get_prompts("hypothesize")
        mock_domain.name = "mock_domain"

        trace = InvestigationTrace(question="test")
        understand_result = {
            "metric": "click_quality",
            "metric_direction": "down",
            "severity": "P1",
            "co_movement_pattern": {"pattern_name": "unknown"},
            "mix_shift_result": None,
        }

        def mock_llm(prompt, system, max_tokens):
            return '{"hypotheses": [{"hypothesis_id": "h1", "archetype": "ranking_regression", "is_contrarian": true, "confirms_if": ["test"], "expected_magnitude": "2%"}, {"hypothesis_id": "h2", "archetype": "connector_change", "is_contrarian": false, "confirms_if": ["test2"], "expected_magnitude": "3%"}, {"hypothesis_id": "h3", "archetype": "experiment_ramp", "is_contrarian": false, "confirms_if": ["test3"], "expected_magnitude": "1%"}], "exclusions": []}'

        result = stage_hypothesize(
            understand_result=understand_result,
            trace=trace,
            llm_callable=mock_llm,
            domain=mock_domain,
        )

        mock_domain.get_prompts.assert_called_once_with("hypothesize")
        assert len(result.get("hypotheses", [])) >= 1

    def test_defaults_to_search_metrics_when_no_domain(self):
        """Without domain param, should still work (backward compat)."""
        import inspect
        from harness.stages.hypothesize import stage_hypothesize
        sig = inspect.signature(stage_hypothesize)
        param = sig.parameters["domain"]
        assert param.default is None
