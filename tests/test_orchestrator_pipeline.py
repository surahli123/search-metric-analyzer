"""Tests for SearchMetricOrchestrator -- the v2 4-stage pipeline.

Tests cover:
1. UNDERSTAND stage happy path (good data -> UnderstandResult)
2. UNDERSTAND stage with bad data quality (-> blocked report)
3. Seam validator called with "UNDERSTAND" stage
4. Trace spans emitted for UNDERSTAND decisions
5. HYPOTHESIZE stage happy path (mock LLM -> HypothesisSet)
6. HYPOTHESIZE corrections loading, trace emission, error handling
7. DISPATCH/SYNTHESIZE raise NotImplementedError
8. Regression: existing orchestrate() function still works

These tests use the same fixture pattern as test_decompose.py --
synthetic rows with 'period' field splitting baseline vs current.
"""

import json
import pytest
from typing import Any, Dict, List

from harness.orchestrator import (
    SearchMetricOrchestrator,
    orchestrate,
    _should_orchestrate,
    _fuse_verdicts,
)
from harness.errors import (
    OrchestratorError,
    StageError,
    LLMError,
    LLMParseError,
    LLMAPIError,
)
from contracts.seam_validator import SeamViolation
from trace.collector import InvestigationTrace


# ---------------------------------------------------------------------------
# Fixtures -- synthetic data for pipeline tests
# ---------------------------------------------------------------------------

def _make_good_rows() -> List[Dict[str, Any]]:
    """Create rows with good data quality that will pass all checks.

    Returns 40 rows: 20 baseline + 20 current.
    Standard tier drops from 0.280 to 0.245 (Click Quality regression).
    Premium tier stays stable at 0.280.
    Data quality fields are healthy (completeness=0.995, freshness=10 min).
    """
    rows = []

    # Baseline period: 20 rows, 50% standard / 50% premium
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

    # Current period: standard tier drops, premium stays flat
    for i in range(20):
        is_standard = i % 2 == 0
        rows.append({
            "period": "current",
            "tenant_tier": "standard" if is_standard else "premium",
            "ai_enablement": "ai_off",
            # Standard tier CQ drops from 0.280 to 0.245 (-12.5%)
            "click_quality_value": 0.245 if is_standard else 0.280,
            "search_quality_success_value": 0.340 if is_standard else 0.378,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            "data_completeness": 0.995,
            "data_freshness_min": 10,
        })

    return rows


def _make_bad_quality_rows() -> List[Dict[str, Any]]:
    """Create rows with FAILING data quality (completeness < 96%).

    This should trigger the UNDERSTAND hard gate -- pipeline halts.
    """
    rows = []
    for i in range(10):
        rows.append({
            "period": "baseline",
            "tenant_tier": "standard",
            "click_quality_value": 0.280,
            "search_quality_success_value": 0.378,
            "ai_trigger": 0.220,
            "ai_success": 0.620,
            # Data completeness below 96% threshold -> FAIL
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
    """Return a valid HypothesisSet JSON string that passes seam validation.

    This is the standard mock LLM response for tests that don't care about
    the specific hypotheses -- they just need HYPOTHESIZE to succeed so
    the pipeline can continue.
    """
    return json.dumps({
        "hypotheses": [
            {
                "hypothesis_id": "hyp_001",
                "archetype": "ranking_regression",
                "priority": 1,
                "confirms_if": ["ranking model deployment logs show change in date range"],
                "rejects_if": ["no model changes in deployment logs"],
                "expected_magnitude": "3-5% drop",
                "source": "data_driven",
                "is_contrarian": False,
            },
            {
                "hypothesis_id": "hyp_002",
                "archetype": "connector_pipeline_change",
                "priority": 2,
                "confirms_if": ["connector health dashboard shows failures"],
                "rejects_if": ["all connectors healthy in monitoring"],
                "expected_magnitude": "2-4% drop",
                "source": "playbook",
                "is_contrarian": False,
            },
            {
                "hypothesis_id": "hyp_003",
                "archetype": "user_behavior_shift",
                "priority": 3,
                "confirms_if": ["query pattern analysis shows shift in intent distribution"],
                "rejects_if": ["query patterns stable over period"],
                "expected_magnitude": "1-3% drop",
                "source": "novel",
                "is_contrarian": True,
            },
        ],
        "exclusions": [
            {
                "archetype": "seasonal",
                "reason": "No calendar effects match this timing",
            },
        ],
        "investigation_context": "Click quality dropped in standard tier, stable in premium. "
        "Investigating ranking, connector, and behavioral explanations.",
    })


def _dummy_llm(prompt: str, system: str, max_tokens: int) -> str:
    """Mock LLM callable that returns valid hypothesis JSON.

    Used by tests that need the full pipeline to work (UNDERSTAND + HYPOTHESIZE).
    Returns valid JSON so HYPOTHESIZE can parse it.
    """
    return _make_valid_hypothesis_json()


# ---------------------------------------------------------------------------
# Error Hierarchy Tests
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    """Test the OrchestratorError hierarchy is properly structured."""

    def test_orchestrator_error_is_base(self):
        """All errors should inherit from OrchestratorError."""
        assert issubclass(StageError, OrchestratorError)
        assert issubclass(LLMError, OrchestratorError)
        assert issubclass(LLMParseError, LLMError)
        assert issubclass(LLMAPIError, LLMError)

    def test_stage_error_captures_stage_name(self):
        """StageError should record which stage failed."""
        err = StageError("failed", stage="UNDERSTAND", violations=["bad data"])
        assert err.stage == "UNDERSTAND"
        assert err.violations == ["bad data"]
        assert "failed" in str(err)

    def test_llm_parse_error_is_not_transient(self):
        """Parse errors are persistent -- retrying won't help."""
        err = LLMParseError("bad json", stage="HYPOTHESIZE", raw_response="not json")
        assert err.is_transient is False
        assert err.raw_response == "not json"

    def test_llm_api_error_is_transient(self):
        """API errors are transient -- retrying usually helps."""
        err = LLMAPIError("timeout", stage="SYNTHESIZE", status_code=503)
        assert err.is_transient is True
        assert err.status_code == 503

    def test_catch_all_orchestrator_errors(self):
        """A broad except OrchestratorError should catch all subtypes."""
        errors = [
            OrchestratorError("base"),
            StageError("stage", stage="UNDERSTAND"),
            LLMError("llm", stage="HYPOTHESIZE"),
            LLMParseError("parse", stage="DISPATCH"),
            LLMAPIError("api", stage="SYNTHESIZE"),
        ]
        for err in errors:
            # All should be catchable as OrchestratorError
            with pytest.raises(OrchestratorError):
                raise err

    def test_error_details_dict(self):
        """Errors should carry optional details dict for debugging."""
        err = OrchestratorError("oops", details={"key": "value"})
        assert err.details == {"key": "value"}

    def test_error_default_details_empty(self):
        """Details should default to empty dict if not provided."""
        err = OrchestratorError("oops")
        assert err.details == {}


# ---------------------------------------------------------------------------
# SearchMetricOrchestrator -- UNDERSTAND Happy Path
# ---------------------------------------------------------------------------


class TestUnderstandHappyPath:
    """Test UNDERSTAND stage with good data -- should produce a valid result."""

    def test_returns_partial_report(self):
        """With UNDERSTAND + HYPOTHESIZE implemented, run() returns a partial report."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "partial"
        assert "UNDERSTAND" in result["stages_completed"]
        assert "HYPOTHESIZE" in result["stages_completed"]
        assert "DISPATCH" in result["stages_remaining"]

    def test_understand_result_has_required_fields(self):
        """UnderstandResult must contain all contract-required fields."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        ur = result["understand_result"]

        # Required fields from the UnderstandResult contract
        assert "question" in ur
        assert "metric" in ur
        assert "direction" in ur
        assert "severity" in ur
        assert "data_quality_status" in ur
        assert "metric_direction" in ur  # IC9 Invisible Decision #1
        assert "co_movement_pattern" in ur
        assert "data_quality_details" in ur

    def test_detects_downward_direction(self):
        """With standard tier dropping, direction should be 'down'."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        ur = result["understand_result"]
        assert ur["direction"] == "down"
        assert ur["metric_direction"] == "down"  # IC9 #1 traced

    def test_data_quality_passes(self):
        """Good data should pass the data quality check."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["understand_result"]["data_quality_status"] == "pass"

    def test_question_preserved_in_result(self):
        """The original question should be preserved in the result."""
        question = "Why did Click Quality drop 6.2% this week?"
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question=question,
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )
        assert result["question"] == question
        assert result["understand_result"]["question"] == question

    def test_includes_decomposition(self):
        """UnderstandResult should include the decomposition for downstream use."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        decomp = result["understand_result"]["decomposition"]
        assert "aggregate" in decomp
        assert "dimensional_breakdown" in decomp

    def test_includes_diagnosis(self):
        """UnderstandResult should include the diagnosis for downstream use."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        diagnosis = result["understand_result"]["diagnosis"]
        assert "primary_hypothesis" in diagnosis
        assert "confidence" in diagnosis


# ---------------------------------------------------------------------------
# SearchMetricOrchestrator -- UNDERSTAND with Bad Data Quality
# ---------------------------------------------------------------------------


class TestUnderstandBadDataQuality:
    """Test UNDERSTAND stage with bad data quality -- should return blocked report."""

    def test_returns_blocked_status(self):
        """Bad data quality should produce a blocked report, not an error."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "blocked"

    def test_blocked_report_has_reason(self):
        """Blocked report should explain WHY the pipeline halted."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert "blocked_reason" in result
        assert len(result["blocked_reason"]) > 0

    def test_blocked_report_has_remediation(self):
        """Blocked report should provide remediation guidance."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert "remediation" in result
        assert "completeness" in result["remediation"].lower()

    def test_blocked_report_has_trace(self):
        """Even blocked reports should include a trace for debugging."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert "trace" in result
        assert "trace_id" in result["trace"]

    def test_no_stages_completed_when_blocked(self):
        """When blocked at UNDERSTAND, no stages should be listed as completed."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert result["stages_completed"] == []

    def test_empty_rows_produces_blocked(self):
        """Empty rows should produce a blocked report (no data to analyze)."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=[],
            metric_field="click_quality_value",
        )
        assert result["status"] == "blocked"


# ---------------------------------------------------------------------------
# Seam Validator Integration
# ---------------------------------------------------------------------------


class TestSeamValidatorCalled:
    """Test that the seam validator is called for the UNDERSTAND stage."""

    def test_seam_validation_recorded_in_trace(self):
        """Trace should contain a seam validation span for UNDERSTAND."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        understand_seams = [
            s for s in seam_validations if s["stage"] == "UNDERSTAND"
        ]
        assert len(understand_seams) >= 1
        assert understand_seams[0]["passed"] is True

    def test_seam_uses_hard_gate_tier(self):
        """UNDERSTAND seam validation should use the 'hard' gate tier."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        understand_seams = [
            s for s in seam_validations if s["stage"] == "UNDERSTAND"
        ]
        assert understand_seams[0]["tier"] == "hard"


# ---------------------------------------------------------------------------
# Trace Emission Tests
# ---------------------------------------------------------------------------


class TestTraceEmission:
    """Test that UNDERSTAND stage emits trace spans for key decisions."""

    def test_trace_has_understand_spans(self):
        """UNDERSTAND stage should emit decision spans."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        understand_spans = [
            s for s in spans if s.get("stage") == "UNDERSTAND"
        ]
        # Should have multiple spans: data quality, metric direction,
        # step change, co-movement, dominant dimension, mix-shift, plus
        # the understand_complete summary span
        assert len(understand_spans) >= 3

    def test_trace_includes_metric_direction_decision(self):
        """IC9 Invisible Decision #1: metric_direction must be traced."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        direction_spans = [
            s for s in spans if s.get("decision") == "metric_direction"
        ]
        assert len(direction_spans) >= 1
        assert direction_spans[0]["value"] == "down"

    def test_trace_includes_data_quality_decision(self):
        """Data quality status should be traced."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        dq_spans = [
            s for s in spans if s.get("decision") == "data_quality_status"
        ]
        assert len(dq_spans) >= 1
        assert dq_spans[0]["value"] == "pass"

    def test_trace_includes_understand_complete_span(self):
        """The orchestrator should emit its own summary span after UNDERSTAND."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        complete_spans = [
            s for s in spans if s.get("decision") == "understand_complete"
        ]
        assert len(complete_spans) == 1
        assert "down" in complete_spans[0]["value"]

    def test_trace_has_valid_trace_id(self):
        """Trace should have a valid trace_id."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )
        trace_dict = result["trace"]
        assert "trace_id" in trace_dict
        assert trace_dict["trace_id"].startswith("inv_")


# ---------------------------------------------------------------------------
# NotImplementedError for Future Stages
# ---------------------------------------------------------------------------


class TestFutureStagesNotImplemented:
    """Verify DISPATCH, SYNTHESIZE raise NotImplementedError.

    Note: HYPOTHESIZE is now implemented (Task 9) -- see TestHypothesizeStage.
    """

    def test_dispatch_raises_not_implemented(self):
        """_stage_dispatch should raise NotImplementedError with message."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        with pytest.raises(NotImplementedError, match="DISPATCH"):
            orch._stage_dispatch({}, {}, None)

    def test_synthesize_raises_not_implemented(self):
        """_stage_synthesize should raise NotImplementedError with message."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        with pytest.raises(NotImplementedError, match="SYNTHESIZE"):
            orch._stage_synthesize({}, {}, None)


# ---------------------------------------------------------------------------
# Regression Tests -- Existing orchestrate() function still works
# ---------------------------------------------------------------------------


class TestExistingOrchestrateRegression:
    """Verify that the existing orchestrate() function is not broken.

    These tests are duplicates of key tests from the existing orchestrator
    test suite, ensuring the v2 class addition didn't break v1 functionality.
    """

    def _fake_agent(self, verdict: str, reason: str = "test"):
        """Create a simple agent callable for testing."""
        def agent(diagnosis_result, hypothesis):
            return {
                "agent": f"test_agent_{verdict}",
                "ran": True,
                "verdict": verdict,
                "reason": reason,
                "queries": [],
                "evidence": [],
                "cost": {"queries": 0, "seconds": 0.0},
            }
        return agent

    def test_orchestrate_skips_when_no_agents(self):
        """orchestrate() should skip when no agents are provided."""
        diagnosis = {
            "decision_status": "diagnosed",
            "confidence": {"level": "Medium"},
            "primary_hypothesis": {"category": "ranking_regression"},
        }
        result = orchestrate(diagnosis, agents=[])
        assert result["orchestrated"] is False
        assert result["fused_verdict"] == "insufficient_evidence"

    def test_orchestrate_skips_high_confidence(self):
        """orchestrate() should skip for high-confidence diagnoses."""
        diagnosis = {
            "decision_status": "diagnosed",
            "confidence": {"level": "High"},
            "primary_hypothesis": {"category": "ranking_regression"},
        }
        agents = [self._fake_agent("confirmed")]
        result = orchestrate(diagnosis, agents)
        assert result["orchestrated"] is False
        assert result["fused_verdict"] == "confirmed"

    def test_orchestrate_runs_agents_and_fuses(self):
        """orchestrate() should run agents and fuse their verdicts."""
        diagnosis = {
            "decision_status": "diagnosed",
            "confidence": {"level": "Medium"},
            "primary_hypothesis": {"category": "ranking_regression"},
        }
        agents = [self._fake_agent("confirmed")]
        result = orchestrate(diagnosis, agents)
        assert result["orchestrated"] is True
        assert result["fused_verdict"] == "confirmed"
        assert len(result["agents_run"]) == 1

    def test_fuse_verdicts_blocked_wins(self):
        """_fuse_verdicts: blocked should override all other verdicts."""
        agents_run = [
            {"agent": "a", "verdict": "confirmed"},
            {"agent": "b", "verdict": "blocked"},
        ]
        verdict, reason = _fuse_verdicts(agents_run)
        assert verdict == "blocked"

    def test_should_orchestrate_gate_logic(self):
        """_should_orchestrate gate logic should work correctly."""
        # Diagnosed + Medium confidence + agents -> True
        assert _should_orchestrate(
            {"decision_status": "diagnosed", "confidence": {"level": "Medium"}},
            [lambda x, y: {}],
        ) is True

        # No agents -> False
        assert _should_orchestrate(
            {"decision_status": "diagnosed", "confidence": {"level": "Medium"}},
            [],
        ) is False


# ---------------------------------------------------------------------------
# Configuration Tests
# ---------------------------------------------------------------------------


class TestOrchestratorConfiguration:
    """Test that configuration is handled correctly."""

    def test_default_config_applied(self):
        """Default config should be applied when none is provided."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        assert orch._config["max_retries"] == 2
        assert orch._config["timeout_seconds"] == 60

    def test_custom_config_overrides_defaults(self):
        """Custom config should override default values."""
        orch = SearchMetricOrchestrator(
            llm_callable=_dummy_llm,
            config={"max_retries": 5, "custom_key": "custom_value"},
        )
        assert orch._config["max_retries"] == 5
        assert orch._config["timeout_seconds"] == 60  # default preserved
        assert orch._config["custom_key"] == "custom_value"

    def test_llm_callable_stored(self):
        """LLM callable should be stored for later use."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        assert orch._llm is _dummy_llm


# ---------------------------------------------------------------------------
# HYPOTHESIZE Stage Tests
# ---------------------------------------------------------------------------


class TestHypothesizeStage:
    """Test HYPOTHESIZE stage -- LLM-based hypothesis generation.

    These tests use mock LLM callables to verify:
    - Valid JSON -> produces HypothesisSet with all required fields
    - Corrections are loaded and passed to LLM prompt
    - IC9 Invisible Decision #2 (hypothesis_inclusion) trace span emitted
    - Seam validation runs with SOFT gate (violations logged, not halted)
    - JSON extraction failure -> StageError
    - At least one contrarian hypothesis required
    """

    def test_hypothesize_produces_hypothesis_set(self):
        """Mock LLM returning valid JSON -> produces HypothesisSet dict."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should complete through HYPOTHESIZE
        assert result["status"] == "partial"
        assert "HYPOTHESIZE" in result["stages_completed"]

        # HypothesisSet should be present in the result
        hyp_set = result["hypothesize_result"]
        assert "hypotheses" in hyp_set
        assert "exclusions" in hyp_set
        assert "investigation_context" in hyp_set

    def test_hypothesize_has_at_least_three_hypotheses(self):
        """HypothesisSet must contain >= 3 hypotheses (seam rule)."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        hypotheses = result["hypothesize_result"]["hypotheses"]
        assert len(hypotheses) >= 3

    def test_hypothesize_hypotheses_have_required_fields(self):
        """Each HypothesisBrief must have all required fields."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        for h in result["hypothesize_result"]["hypotheses"]:
            assert "hypothesis_id" in h
            assert "archetype" in h
            assert "priority" in h
            assert "confirms_if" in h
            assert "rejects_if" in h
            assert "expected_magnitude" in h
            assert "source" in h
            assert "is_contrarian" in h

    def test_hypothesize_has_contrarian(self):
        """At least one hypothesis must be contrarian."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        hypotheses = result["hypothesize_result"]["hypotheses"]
        contrarians = [h for h in hypotheses if h.get("is_contrarian")]
        assert len(contrarians) >= 1

    def test_hypothesize_has_exclusions(self):
        """HypothesisSet should include exclusions with reasons."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        exclusions = result["hypothesize_result"]["exclusions"]
        assert len(exclusions) >= 1
        for e in exclusions:
            assert "archetype" in e
            assert "reason" in e

    def test_hypothesize_has_investigation_context(self):
        """HypothesisSet should include investigation_context string."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        context = result["hypothesize_result"]["investigation_context"]
        assert isinstance(context, str)
        assert len(context) > 0


class TestHypothesizeCorrections:
    """Test that corrections are loaded and passed to the LLM prompt."""

    def test_corrections_included_in_prompt(self):
        """The LLM prompt should contain corrections when they exist.

        We verify by capturing what the mock LLM receives and checking
        that the prompt mentions corrections.
        """
        captured_prompts = []

        def capturing_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Mock LLM that captures prompts for inspection."""
            captured_prompts.append(prompt)
            return _make_valid_hypothesis_json()

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # The prompt should mention corrections section
        # (even if no corrections are found, the section header is present)
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "CORRECTION" in prompt.upper()

    def test_system_prompt_includes_domain_context(self):
        """System prompt should include Enterprise Search domain context."""
        captured_system = []

        def capturing_llm(prompt: str, system: str, max_tokens: int) -> str:
            captured_system.append(system)
            return _make_valid_hypothesis_json()

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        system = captured_system[0]
        # System prompt should mention AI adoption trap
        assert "AI" in system
        # Should mention hypothesis priority order
        assert "priority" in system.lower()
        # Should require JSON output
        assert "JSON" in system

    def test_prompt_includes_metric_info(self):
        """User prompt should include metric name, direction, severity."""
        captured_prompts = []

        def capturing_llm(prompt: str, system: str, max_tokens: int) -> str:
            captured_prompts.append(prompt)
            return _make_valid_hypothesis_json()

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run(
            question="CQ drop investigation",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        prompt = captured_prompts[0]
        assert "click_quality_value" in prompt
        assert "down" in prompt.lower()

    def test_prompt_includes_understand_context(self):
        """User prompt should include token-budgeted UNDERSTAND context."""
        captured_prompts = []

        def capturing_llm(prompt: str, system: str, max_tokens: int) -> str:
            captured_prompts.append(prompt)
            return _make_valid_hypothesis_json()

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        prompt = captured_prompts[0]
        # Should include the UNDERSTAND stage context
        assert "UNDERSTAND" in prompt


class TestHypothesizeTraceEmission:
    """Test IC9 Invisible Decision #2 trace span (hypothesis_inclusion)."""

    def test_hypothesis_inclusion_span_emitted(self):
        """Trace should contain a hypothesis_inclusion decision span."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        inclusion_spans = [
            s for s in spans if s.get("decision") == "hypothesis_inclusion"
        ]
        # IC9 Invisible Decision #2 must be traced
        assert len(inclusion_spans) == 1

    def test_hypothesis_inclusion_span_has_included_and_excluded(self):
        """hypothesis_inclusion span should track what was included and excluded."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        inclusion_spans = [
            s for s in spans if s.get("decision") == "hypothesis_inclusion"
        ]
        span = inclusion_spans[0]
        # Value should contain included and excluded lists
        assert "included" in span["value"]
        assert "excluded" in span["value"]
        assert len(span["value"]["included"]) >= 3
        assert len(span["value"]["excluded"]) >= 1

    def test_hypothesis_inclusion_span_is_llm_generated(self):
        """hypothesis_inclusion span should be in the llm_generated swimlane."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        inclusion_spans = [
            s for s in spans if s.get("decision") == "hypothesis_inclusion"
        ]
        span = inclusion_spans[0]
        assert span["swimlane"] == "llm_generated"
        assert span["code_enforced"] is False

    def test_hypothesis_inclusion_in_invisible_decisions_summary(self):
        """hypothesis_inclusion should appear in the trace summary's invisible_decisions."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        invisible = trace_dict.get("summary", {}).get("invisible_decisions_traced", [])
        assert "hypothesis_inclusion" in invisible


class TestHypothesizeSeamValidation:
    """Test HYPOTHESIZE seam validation (SOFT gate)."""

    def test_seam_validation_recorded_in_trace(self):
        """Trace should contain a seam validation span for HYPOTHESIZE."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        hyp_seams = [
            s for s in seam_validations if s["stage"] == "HYPOTHESIZE"
        ]
        assert len(hyp_seams) >= 1

    def test_seam_uses_soft_gate_tier(self):
        """HYPOTHESIZE seam validation should use the 'soft' gate tier."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        hyp_seams = [
            s for s in seam_validations if s["stage"] == "HYPOTHESIZE"
        ]
        assert hyp_seams[0]["tier"] == "soft"

    def test_soft_gate_continues_on_violation(self):
        """SOFT gate should log violations but NOT halt the pipeline.

        We use a mock LLM that returns only 2 hypotheses (violates min 3 rule)
        to trigger a seam violation. The pipeline should continue.
        """
        def two_hypothesis_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Returns only 2 hypotheses -- violates rule_min_three_hypotheses."""
            return json.dumps({
                "hypotheses": [
                    {
                        "hypothesis_id": "hyp_001",
                        "archetype": "ranking_regression",
                        "priority": 1,
                        "confirms_if": ["ranking logs show change"],
                        "rejects_if": ["no changes"],
                        "expected_magnitude": "3-5% drop",
                        "source": "data_driven",
                        "is_contrarian": False,
                    },
                    {
                        "hypothesis_id": "hyp_002",
                        "archetype": "user_behavior_shift",
                        "priority": 2,
                        "confirms_if": ["query patterns shifted"],
                        "rejects_if": ["patterns stable"],
                        "expected_magnitude": "1-3% drop",
                        "source": "novel",
                        "is_contrarian": True,
                    },
                ],
                "exclusions": [],
                "investigation_context": "Only 2 hypotheses generated.",
            })

        orch = SearchMetricOrchestrator(llm_callable=two_hypothesis_llm)
        # Should NOT raise -- SOFT gate continues
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should still produce a result
        assert result["status"] == "partial"
        assert "HYPOTHESIZE" in result["stages_completed"]

        # But seam validation should record the violation
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        hyp_seams = [
            s for s in seam_validations if s["stage"] == "HYPOTHESIZE"
        ]
        assert hyp_seams[0]["passed"] is False
        assert len(hyp_seams[0]["violations"]) > 0


class TestHypothesizeErrorHandling:
    """Test HYPOTHESIZE error handling -- JSON parse failure, LLM API errors."""

    def test_json_parse_failure_raises_stage_error(self):
        """If LLM returns unparseable text, should raise StageError."""
        def bad_json_llm(prompt: str, system: str, max_tokens: int) -> str:
            return "This is not JSON at all. Just plain text."

        orch = SearchMetricOrchestrator(llm_callable=bad_json_llm)
        with pytest.raises(StageError) as exc_info:
            orch.run(
                question="CQ drop",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )
        assert exc_info.value.stage == "HYPOTHESIZE"
        assert "JSON" in str(exc_info.value)

    def test_llm_api_error_propagates(self):
        """If LLM call fails with LLMAPIError, it should propagate."""
        def failing_llm(prompt: str, system: str, max_tokens: int) -> str:
            raise LLMAPIError(
                "API timeout", stage="HYPOTHESIZE", status_code=503
            )

        orch = SearchMetricOrchestrator(llm_callable=failing_llm)
        with pytest.raises(LLMAPIError):
            orch.run(
                question="CQ drop",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )

    def test_stage_error_from_parse_is_catchable_as_orchestrator_error(self):
        """StageError from parse failure should be catchable as OrchestratorError."""
        def bad_json_llm(prompt: str, system: str, max_tokens: int) -> str:
            return "not json"

        orch = SearchMetricOrchestrator(llm_callable=bad_json_llm)
        with pytest.raises(OrchestratorError):
            orch.run(
                question="CQ drop",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )

    def test_llm_response_as_list_normalized_to_dict(self):
        """If LLM returns a JSON list, it should be normalized into HypothesisSet."""
        def list_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Returns a list instead of a dict -- should be normalized."""
            return json.dumps([
                {
                    "hypothesis_id": "hyp_001",
                    "archetype": "ranking_regression",
                    "priority": 1,
                    "confirms_if": ["ranking logs show change"],
                    "rejects_if": ["no changes"],
                    "expected_magnitude": "3-5% drop",
                    "source": "data_driven",
                    "is_contrarian": False,
                },
                {
                    "hypothesis_id": "hyp_002",
                    "archetype": "connector_pipeline_change",
                    "priority": 2,
                    "confirms_if": ["connector health check"],
                    "rejects_if": ["all healthy"],
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
            ])

        orch = SearchMetricOrchestrator(llm_callable=list_llm)
        result = orch.run(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "partial"
        hyp_set = result["hypothesize_result"]
        assert len(hyp_set["hypotheses"]) == 3
        assert isinstance(hyp_set["exclusions"], list)
