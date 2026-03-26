"""Tests for SearchMetricOrchestrator -- the 5-stage pipeline.

Tests cover:
1. UNDERSTAND stage happy path (good data -> UnderstandResult)
2. UNDERSTAND stage with bad data quality (-> blocked report)
3. Seam validator called with "UNDERSTAND" stage
4. Trace spans emitted for UNDERSTAND decisions
5. HYPOTHESIZE stage happy path (mock LLM -> HypothesisSet)
6. HYPOTHESIZE corrections loading, trace emission, error handling
7. DISPATCH stage (LLM-based investigation, context_construction trace)
8. SYNTHESIZE stage (LLM report generation, RETRY(1) then SOFT gate)
9. Full pipeline end-to-end (all 4 stages, all 4 IC9 decisions traced)
10. run() integration tests (QUESTION_PARSE + mode selection + pipeline)

These tests use the same fixture pattern as test_decompose.py --
synthetic rows with 'period' field splitting baseline vs current.

NOTE: Most pipeline tests use run_pipeline_only() which skips
QUESTION_PARSE and mode selection (direct 4-stage pipeline).
The run() integration tests cover the full 5-stage flow.
"""

import json
import pytest
from typing import Any, Dict, List

from harness.orchestrator import SearchMetricOrchestrator
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


def _make_valid_finding_json(hypothesis_id: str = "hyp_001") -> str:
    """Return a valid SubAgentFinding JSON string for DISPATCH tests.

    Each finding has at least one evidence item with real data values,
    which satisfies the rule_each_finding_has_evidence seam rule.
    """
    return json.dumps({
        "agent_name": "llm_investigator",
        "hypothesis_id": hypothesis_id,
        "verdict": "confirmed",
        "confidence": 0.75,
        "evidence": [
            {"metric": "click_quality_value", "value": 0.245, "delta": "-12.5%", "direction": "down"}
        ],
        "narrative": f"Investigation of {hypothesis_id}: Evidence supports the hypothesis. "
                     f"Click quality dropped significantly in the standard tier.",
        "adjacent_observations": ["Premium tier remained stable."],
    })


def _make_valid_synthesis_json() -> str:
    """Return a valid SynthesisReport JSON string for SYNTHESIZE tests.

    Includes all 7 mandatory sections, upgrade_condition, and at least
    one recommended action with owner. Passes all SYNTHESIZE seam rules.
    """
    return json.dumps({
        "tldr": "Click Quality dropped 12.5% in the standard tier due to a ranking "
                "model regression. Premium tier was unaffected, confirming the issue "
                "is isolated to standard-tier ranking.",
        "confidence_grade": "Medium",
        "severity": "P1",
        "root_cause": "Ranking model regression in standard tier. The model update "
                      "deployed on Tuesday introduced a ranking signal that penalizes "
                      "navigational queries in the standard tier.",
        "dimensional_breakdown": "Standard tier: -12.5% (n=2400 queries). "
                                  "Premium tier: stable (n=1800 queries). "
                                  "AI-enabled segments were not affected.",
        "hypothesis_and_evidence": "Three hypotheses were investigated. "
                                    "Ranking regression was confirmed with strong evidence "
                                    "(model deployment logs match timing, magnitude consistent). "
                                    "Connector pipeline change was rejected (all connectors healthy). "
                                    "User behavior shift was inconclusive (insufficient data).",
        "validation_summary": "Cross-check: the timing of the drop aligns with the model "
                               "deployment log entry. Magnitude is consistent with historical "
                               "ranking regressions (typically 8-15% for standard tier). "
                               "Premium tier stability rules out platform-wide issues.",
        "recommended_actions": [
            {
                "action": "Roll back the ranking model to the previous version",
                "owner": "Eng Lead",
                "priority": "immediate",
                "rationale": "Standard tier CQ is down 12.5% since deployment. "
                             "Rollback is the fastest path to recovery.",
            },
            {
                "action": "Add regression test for navigational query ranking in standard tier",
                "owner": "Search Platform",
                "priority": "this_sprint",
                "rationale": "Prevent recurrence of this failure mode in future deployments.",
            },
        ],
        "upgrade_condition": "Would upgrade to High confidence if deployment logs "
                             "confirm the exact model version change matches the timing "
                             "of the CQ drop within a 1-hour window.",
        "completeness_warnings": [],
    })


def _dummy_llm(prompt: str, system: str, max_tokens: int) -> str:
    """Mock LLM callable that returns valid JSON for all pipeline stages.

    Routes to the appropriate JSON response based on the system prompt content:
    - HYPOTHESIZE: returns valid HypothesisSet
    - DISPATCH: returns valid SubAgentFinding
    - SYNTHESIZE: returns valid SynthesisReport
    """
    # DISPATCH: investigating a specific hypothesis
    if "investigating a specific hypothesis" in system.lower():
        # Extract hypothesis ID from the prompt
        hyp_id = "hyp_001"
        for line in prompt.split("\n"):
            if "ID:" in line:
                hyp_id = line.split("ID:")[-1].strip()
                break
        return _make_valid_finding_json(hyp_id)

    # SYNTHESIZE: writing the final investigation report
    if "final" in system.lower() and "investigation report" in system.lower():
        return _make_valid_synthesis_json()

    # HYPOTHESIZE: default
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

    def test_returns_complete_report(self):
        """With all 4 stages implemented, run() returns a complete report."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "complete"
        assert "UNDERSTAND" in result["stages_completed"]
        assert "HYPOTHESIZE" in result["stages_completed"]
        assert "DISPATCH" in result["stages_completed"]
        assert "SYNTHESIZE" in result["stages_completed"]

    def test_understand_result_has_required_fields(self):
        """UnderstandResult must contain all contract-required fields."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
            question=question,
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )
        assert result["question"] == question
        assert result["understand_result"]["question"] == question

    def test_includes_decomposition(self):
        """UnderstandResult should include the decomposition for downstream use."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "blocked"

    def test_blocked_report_has_reason(self):
        """Blocked report should explain WHY the pipeline halted."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert "blocked_reason" in result
        assert len(result["blocked_reason"]) > 0

    def test_blocked_report_has_remediation(self):
        """Blocked report should provide remediation guidance."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert "remediation" in result
        assert "completeness" in result["remediation"].lower()

    def test_blocked_report_has_trace(self):
        """Even blocked reports should include a trace for debugging."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert "trace" in result
        assert "trace_id" in result["trace"]

    def test_no_stages_completed_when_blocked(self):
        """When blocked at UNDERSTAND, no stages should be listed as completed."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert result["stages_completed"] == []

    def test_empty_rows_produces_blocked(self):
        """Empty rows should produce a blocked report (no data to analyze)."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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


class TestAllStagesImplemented:
    """Verify DISPATCH and SYNTHESIZE are now implemented (no more NotImplementedError)."""

    def test_dispatch_is_implemented(self):
        """stage_dispatch should raise StageError for empty hypotheses, not NotImplementedError."""
        from harness.stages import stage_dispatch
        # It should raise StageError (no hypotheses), not NotImplementedError
        with pytest.raises(StageError, match="DISPATCH"):
            trace = InvestigationTrace(question="test")
            stage_dispatch(
                hypothesis_set={"hypotheses": []},
                understand_result={},
                trace=trace,
                llm_callable=_dummy_llm,
                config={},
            )


# ---------------------------------------------------------------------------
# v1 orchestrate() function was DELETED in the stage extraction refactor.
# Tests were in test_agent_orchestrator.py (also deleted).
# ---------------------------------------------------------------------------


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
        result = orch.run_pipeline_only(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should complete through all stages
        assert result["status"] == "complete"
        assert "HYPOTHESIZE" in result["stages_completed"]

        # HypothesisSet should be present in the result
        hyp_set = result["hypothesize_result"]
        assert "hypotheses" in hyp_set
        assert "exclusions" in hyp_set
        assert "investigation_context" in hyp_set

    def test_hypothesize_has_at_least_three_hypotheses(self):
        """HypothesisSet must contain >= 3 hypotheses (seam rule)."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        that the first prompt (HYPOTHESIZE) mentions corrections.
        """
        captured_prompts = []

        def capturing_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Mock LLM that captures prompts, delegates to _dummy_llm for responses."""
            captured_prompts.append(prompt)
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # The first prompt (HYPOTHESIZE) should mention corrections section
        # (even if no corrections are found, the section header is present)
        assert len(captured_prompts) >= 1
        prompt = captured_prompts[0]
        assert "CORRECTION" in prompt.upper()

    def test_system_prompt_includes_domain_context(self):
        """System prompt should include Enterprise Search domain context."""
        captured_system = []

        def capturing_llm(prompt: str, system: str, max_tokens: int) -> str:
            captured_system.append(system)
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # First system prompt is for HYPOTHESIZE
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
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run_pipeline_only(
            question="CQ drop investigation",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # First prompt is for HYPOTHESIZE
        prompt = captured_prompts[0]
        assert "click_quality_value" in prompt
        assert "down" in prompt.lower()

    def test_prompt_includes_understand_context(self):
        """User prompt should include token-budgeted UNDERSTAND context."""
        captured_prompts = []

        def capturing_llm(prompt: str, system: str, max_tokens: int) -> str:
            captured_prompts.append(prompt)
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=capturing_llm)
        orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # First prompt is for HYPOTHESIZE
        prompt = captured_prompts[0]
        # Should include the UNDERSTAND stage context
        assert "UNDERSTAND" in prompt


class TestHypothesizeTraceEmission:
    """Test IC9 Invisible Decision #2 trace span (hypothesis_inclusion)."""

    def test_hypothesis_inclusion_span_emitted(self):
        """Trace should contain a hypothesis_inclusion decision span."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        result = orch.run_pipeline_only(
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
        call_count = {"n": 0}

        def two_hypothesis_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Returns only 2 hypotheses on first call -- violates rule_min_three_hypotheses.
            Delegates to _dummy_llm for DISPATCH and SYNTHESIZE calls."""
            call_count["n"] += 1
            if call_count["n"] == 1:
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
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=two_hypothesis_llm)
        # Should NOT raise -- SOFT gate continues
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should still produce a result
        assert result["status"] == "complete"
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
            orch.run_pipeline_only(
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
            orch.run_pipeline_only(
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
            orch.run_pipeline_only(
                question="CQ drop",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )

    def test_llm_response_as_list_normalized_to_dict(self):
        """If LLM returns a JSON list, it should be normalized into HypothesisSet."""
        call_count = {"n": 0}

        def list_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Returns a list on first call (HYPOTHESIZE), delegates for other stages."""
            call_count["n"] += 1
            # First call is HYPOTHESIZE -- return a list
            if call_count["n"] == 1:
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
            # Subsequent calls (DISPATCH, SYNTHESIZE) -- delegate to _dummy_llm
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=list_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "complete"
        hyp_set = result["hypothesize_result"]
        assert len(hyp_set["hypotheses"]) == 3
        assert isinstance(hyp_set["exclusions"], list)


# ---------------------------------------------------------------------------
# DISPATCH Stage Tests
# ---------------------------------------------------------------------------


class TestDispatchStage:
    """Test DISPATCH stage -- LLM-based hypothesis investigation."""

    def test_dispatch_produces_finding_set(self):
        """DISPATCH should produce a FindingSet with findings."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "complete"
        assert "DISPATCH" in result["stages_completed"]
        assert "dispatch_result" in result

        finding_set = result["dispatch_result"]
        assert "findings" in finding_set
        assert len(finding_set["findings"]) >= 1

    def test_dispatch_findings_have_evidence(self):
        """Each finding should have at least one evidence item."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        for f in result["dispatch_result"]["findings"]:
            assert "evidence" in f
            assert len(f["evidence"]) >= 1

    def test_dispatch_findings_have_required_fields(self):
        """Each finding must have all required SubAgentFinding fields."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        for f in result["dispatch_result"]["findings"]:
            assert "agent_name" in f
            assert "hypothesis_id" in f
            assert "verdict" in f
            assert "confidence" in f
            assert "evidence" in f
            assert "narrative" in f

    def test_dispatch_has_context_construction_trace(self):
        """FindingSet should include the context construction trace."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert "context_construction_trace" in result["dispatch_result"]
        assert len(result["dispatch_result"]["context_construction_trace"]) > 0


class TestDispatchTraceEmission:
    """Test IC9 Invisible Decision #3 trace span (context_construction)."""

    def test_context_construction_span_emitted(self):
        """Trace should contain a context_construction decision span."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        ctx_spans = [
            s for s in spans if s.get("decision") == "context_construction"
        ]
        assert len(ctx_spans) == 1
        assert ctx_spans[0]["stage"] == "DISPATCH"
        assert ctx_spans[0]["code_enforced"] is False

    def test_context_construction_in_invisible_decisions_summary(self):
        """context_construction should appear in the trace summary."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        invisible = trace_dict.get("summary", {}).get("invisible_decisions_traced", [])
        assert "context_construction" in invisible


class TestDispatchSeamValidation:
    """Test DISPATCH seam validation (SOFT gate)."""

    def test_dispatch_seam_recorded_in_trace(self):
        """Trace should contain a seam validation span for DISPATCH."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        dispatch_seams = [
            s for s in seam_validations if s["stage"] == "DISPATCH"
        ]
        assert len(dispatch_seams) >= 1
        assert dispatch_seams[0]["tier"] == "soft"


class TestDispatchErrorHandling:
    """Test DISPATCH error handling."""

    def test_empty_hypothesis_set_raises_stage_error(self):
        """DISPATCH with no hypotheses should raise StageError."""
        from harness.stages import stage_dispatch
        trace = InvestigationTrace(question="test")
        with pytest.raises(StageError, match="DISPATCH"):
            stage_dispatch(
                hypothesis_set={"hypotheses": []},
                understand_result={},
                trace=trace,
                llm_callable=_dummy_llm,
                config={},
            )


# ---------------------------------------------------------------------------
# SYNTHESIZE Stage Tests
# ---------------------------------------------------------------------------


class TestSynthesizeStage:
    """Test SYNTHESIZE stage -- LLM-based report generation with RETRY gate."""

    def test_synthesize_produces_report(self):
        """SYNTHESIZE should produce a SynthesisReport dict."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "complete"
        assert "SYNTHESIZE" in result["stages_completed"]
        assert "synthesis" in result

    def test_synthesize_has_all_mandatory_sections(self):
        """SynthesisReport must contain all 7 mandatory sections."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        synthesis = result["synthesis"]

        mandatory = [
            "tldr", "confidence_grade", "severity", "root_cause",
            "dimensional_breakdown", "hypothesis_and_evidence", "validation_summary",
        ]
        for section in mandatory:
            assert section in synthesis, f"Missing mandatory section: {section}"
            assert len(synthesis[section]) > 0, f"Empty mandatory section: {section}"

    def test_synthesize_has_upgrade_condition(self):
        """SynthesisReport must include upgrade_condition."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        synthesis = result["synthesis"]
        assert "upgrade_condition" in synthesis
        assert len(synthesis["upgrade_condition"]) > 0

    def test_synthesize_has_recommended_actions(self):
        """SynthesisReport should include recommended actions with owners."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        actions = result["synthesis"]["recommended_actions"]
        assert len(actions) >= 1
        for a in actions:
            assert "action" in a
            assert "owner" in a
            assert "priority" in a

    def test_synthesize_has_investigation_id(self):
        """SynthesisReport should include the trace's investigation_id."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        synthesis = result["synthesis"]
        assert "investigation_id" in synthesis
        # investigation_id should match the trace's trace_id
        assert synthesis["investigation_id"] == result["trace"]["trace_id"]

    def test_synthesize_has_completeness_warnings(self):
        """SynthesisReport should include completeness_warnings (even if empty)."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        synthesis = result["synthesis"]
        assert "completeness_warnings" in synthesis
        assert isinstance(synthesis["completeness_warnings"], list)


class TestSynthesizeRetryGate:
    """Test SYNTHESIZE RETRY(1) then SOFT gate logic."""

    def test_retry_on_first_validation_failure(self):
        """If first attempt fails validation, SYNTHESIZE should retry with violations."""
        call_count = {"n": 0}

        def retry_testing_llm(prompt: str, system: str, max_tokens: int) -> str:
            """First SYNTHESIZE call returns incomplete report (missing sections).
            Second SYNTHESIZE call returns complete report.
            Other stages delegate to _dummy_llm."""
            # Use system prompt to detect SYNTHESIZE calls
            if "final" in system.lower() and "investigation report" in system.lower():
                call_count["n"] += 1
                if call_count["n"] == 1:
                    # First attempt: missing mandatory sections to trigger retry
                    return json.dumps({
                        "tldr": "CQ dropped.",
                        "confidence_grade": "Medium",
                        "severity": "P1",
                        "root_cause": "",  # empty -- triggers validation failure
                        "dimensional_breakdown": "",  # empty -- triggers failure
                        "hypothesis_and_evidence": "",  # empty -- triggers failure
                        "validation_summary": "",  # empty -- triggers failure
                        "recommended_actions": [],
                        "upgrade_condition": "",
                        "completeness_warnings": [],
                    })
                else:
                    # Second attempt (retry): return complete report
                    return _make_valid_synthesis_json()
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=retry_testing_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should complete successfully after retry
        assert result["status"] == "complete"
        assert "SYNTHESIZE" in result["stages_completed"]

        # The LLM should have been called twice for SYNTHESIZE
        assert call_count["n"] == 2

        # The second call should have received violation feedback
        # (verified by the fact that it succeeded)
        synthesis = result["synthesis"]
        assert len(synthesis["root_cause"]) > 0

    def test_retry_prompt_includes_violations(self):
        """On retry, the prompt should include the violation messages."""
        captured_prompts = []
        call_count = {"n": 0}

        def capturing_retry_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Captures SYNTHESIZE prompts to verify retry includes violations."""
            if "final" in system.lower() and "investigation report" in system.lower():
                call_count["n"] += 1
                captured_prompts.append(prompt)
                if call_count["n"] == 1:
                    # First attempt: missing sections
                    return json.dumps({
                        "tldr": "", "confidence_grade": "", "severity": "",
                        "root_cause": "", "dimensional_breakdown": "",
                        "hypothesis_and_evidence": "", "validation_summary": "",
                        "recommended_actions": [], "upgrade_condition": "",
                        "completeness_warnings": [],
                    })
                else:
                    return _make_valid_synthesis_json()
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=capturing_retry_llm)
        orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # There should be 2 SYNTHESIZE prompts (original + retry)
        assert len(captured_prompts) == 2
        # The retry prompt should contain "issues" or "violations"
        retry_prompt = captured_prompts[1]
        assert "issues" in retry_prompt.lower() or "MUST be fixed" in retry_prompt

    def test_soft_fallback_on_double_failure(self):
        """If both attempts fail validation, SYNTHESIZE should continue with best-effort."""
        def always_incomplete_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Always returns an incomplete SynthesisReport (missing sections)."""
            if "final" in system.lower() and "investigation report" in system.lower():
                return json.dumps({
                    "tldr": "CQ dropped.",
                    "confidence_grade": "Medium",
                    "severity": "P1",
                    "root_cause": "",  # always empty
                    "dimensional_breakdown": "",
                    "hypothesis_and_evidence": "",
                    "validation_summary": "",
                    "recommended_actions": [],
                    "upgrade_condition": "",
                    "completeness_warnings": [],
                })
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=always_incomplete_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should STILL complete -- SOFT fallback
        assert result["status"] == "complete"
        assert "SYNTHESIZE" in result["stages_completed"]

        # The synthesis should have completeness_warnings from the soft fallback
        synthesis = result["synthesis"]
        assert len(synthesis["completeness_warnings"]) > 0
        # Warnings should mention the seam violation
        warning_text = " ".join(synthesis["completeness_warnings"])
        assert "SEAM VIOLATION" in warning_text


class TestSynthesizeTraceEmission:
    """Test IC9 Invisible Decision #4 trace span (narrative_selection)."""

    def test_narrative_selection_span_emitted(self):
        """Trace should contain a narrative_selection decision span."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        narrative_spans = [
            s for s in spans if s.get("decision") == "narrative_selection"
        ]
        assert len(narrative_spans) == 1

    def test_narrative_selection_span_is_llm_generated(self):
        """narrative_selection span should be in the llm_generated swimlane."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        narrative_spans = [
            s for s in spans if s.get("decision") == "narrative_selection"
        ]
        span = narrative_spans[0]
        assert span["swimlane"] == "llm_generated"
        assert span["code_enforced"] is False
        assert span["stage"] == "SYNTHESIZE"

    def test_narrative_selection_has_report_summary(self):
        """narrative_selection span value should summarize the report choices."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        spans = trace_dict.get("spans", [])
        narrative_spans = [
            s for s in spans if s.get("decision") == "narrative_selection"
        ]
        value = narrative_spans[0]["value"]
        assert "confidence_grade" in value
        assert "severity" in value
        assert "action_count" in value
        assert "has_upgrade_condition" in value

    def test_narrative_selection_in_invisible_decisions_summary(self):
        """narrative_selection should appear in the trace summary's invisible_decisions."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        invisible = trace_dict.get("summary", {}).get("invisible_decisions_traced", [])
        assert "narrative_selection" in invisible


class TestSynthesizeSeamValidation:
    """Test SYNTHESIZE seam validation."""

    def test_synthesize_seam_recorded_in_trace(self):
        """Trace should contain a seam validation span for SYNTHESIZE."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        synth_seams = [
            s for s in seam_validations if s["stage"] == "SYNTHESIZE"
        ]
        assert len(synth_seams) >= 1
        assert synth_seams[0]["tier"] == "retry"


# ---------------------------------------------------------------------------
# Full Pipeline End-to-End Tests
# ---------------------------------------------------------------------------


class TestFullPipelineEndToEnd:
    """Test the complete 4-stage pipeline end-to-end with mock LLM."""

    def test_full_pipeline_happy_path(self):
        """Full pipeline (UNDERSTAND -> HYPOTHESIZE -> DISPATCH -> SYNTHESIZE) produces
        a complete report with all expected sections."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="Click Quality dropped 6.2% WoW for standard tier",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # Status and stages
        assert result["status"] == "complete"
        assert result["stages_completed"] == [
            "UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"
        ]

        # All stage outputs present
        assert "understand_result" in result
        assert "hypothesize_result" in result
        assert "dispatch_result" in result
        assert "synthesis" in result
        assert "trace" in result

        # UNDERSTAND populated
        ur = result["understand_result"]
        assert ur["direction"] == "down"
        assert ur["data_quality_status"] == "pass"

        # HYPOTHESIZE populated
        hyps = result["hypothesize_result"]["hypotheses"]
        assert len(hyps) >= 3

        # DISPATCH populated
        findings = result["dispatch_result"]["findings"]
        assert len(findings) >= 1
        assert all(f.get("evidence") for f in findings)

        # SYNTHESIZE populated
        synthesis = result["synthesis"]
        assert len(synthesis["tldr"]) > 0
        assert synthesis["confidence_grade"] in ("High", "Medium", "Low")
        assert synthesis["severity"] in ("P0", "P1", "P2", "normal")
        assert len(synthesis["root_cause"]) > 0
        assert len(synthesis["recommended_actions"]) >= 1
        assert len(synthesis["upgrade_condition"]) > 0

    def test_full_pipeline_trace_has_all_four_invisible_decisions(self):
        """The trace should record all 4 IC9 Invisible Decisions."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        invisible = trace_dict.get("summary", {}).get("invisible_decisions_traced", [])

        # All 4 IC9 Invisible Decisions must be present
        assert "metric_direction" in invisible       # IC9 #1 (UNDERSTAND)
        assert "hypothesis_inclusion" in invisible    # IC9 #2 (HYPOTHESIZE)
        assert "context_construction" in invisible    # IC9 #3 (DISPATCH)
        assert "narrative_selection" in invisible     # IC9 #4 (SYNTHESIZE)

    def test_full_pipeline_trace_has_seams_for_all_stages(self):
        """The trace should contain seam validation spans for all 4 stages."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_dict = result["trace"]
        seam_validations = trace_dict.get("seam_validations", [])
        stages_with_seams = set(s["stage"] for s in seam_validations)

        assert "UNDERSTAND" in stages_with_seams
        assert "HYPOTHESIZE" in stages_with_seams
        assert "DISPATCH" in stages_with_seams
        assert "SYNTHESIZE" in stages_with_seams

    def test_full_pipeline_investigation_id_consistent(self):
        """The investigation_id should be consistent across trace and synthesis."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ drop",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        trace_id = result["trace"]["trace_id"]
        synthesis_id = result["synthesis"]["investigation_id"]
        assert trace_id == synthesis_id
        assert trace_id.startswith("inv_")


# ---------------------------------------------------------------------------
# Integration Tests — Error Handling (Task 12)
# ---------------------------------------------------------------------------


class TestErrorHandlingIntegration:
    """Test error handling across the full pipeline.

    These tests verify that errors at each stage propagate correctly,
    with the right error type and the right stage annotation. This ensures
    the caller can distinguish between a HYPOTHESIZE parse failure and a
    DISPATCH timeout — different errors require different remediation.
    """

    def test_invalid_json_at_hypothesize_raises_stage_error(self):
        """LLM returning invalid JSON at HYPOTHESIZE -> StageError with stage='HYPOTHESIZE'.

        This is the most common LLM failure mode: the model ignores JSON
        instructions and returns prose. The pipeline should fail fast with
        a clear stage annotation so the caller knows WHICH stage broke.
        """
        def bad_json_at_hypothesize(prompt: str, system: str, max_tokens: int) -> str:
            """Returns garbage at HYPOTHESIZE stage, valid JSON elsewhere."""
            # HYPOTHESIZE is the first LLM call -- return invalid JSON
            if "hypothes" in system.lower() or "generate" in system.lower():
                return "I think the metric dropped because of a ranking change. Let me explain..."
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=bad_json_at_hypothesize)
        with pytest.raises(StageError) as exc_info:
            orch.run_pipeline_only(
                question="CQ dropped 6% WoW",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )
        # Stage annotation must be HYPOTHESIZE, not UNDERSTAND or DISPATCH
        assert exc_info.value.stage == "HYPOTHESIZE"
        # Error message should mention JSON extraction failure
        assert "JSON" in str(exc_info.value)

    def test_llm_timeout_at_dispatch_produces_inconclusive_findings(self):
        """LLM timing out at DISPATCH -> graceful degradation (inconclusive findings).

        DISPATCH catches individual hypothesis investigation failures and records
        them as inconclusive. If ALL investigations fail, it raises StageError.
        This test verifies the all-failed case (which is the graceful degradation
        path — the pipeline stops at DISPATCH with a clear error).
        """
        call_count = {"n": 0}

        def timeout_at_dispatch(prompt: str, system: str, max_tokens: int) -> str:
            """Times out at DISPATCH (investigating hypothesis), works for other stages."""
            # DISPATCH uses a system prompt about "investigating a specific hypothesis"
            if "investigating a specific hypothesis" in system.lower():
                raise LLMAPIError(
                    "Request timed out", stage="DISPATCH", status_code=504
                )
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=timeout_at_dispatch)
        # All hypothesis investigations will fail -> StageError from DISPATCH
        with pytest.raises(StageError) as exc_info:
            orch.run_pipeline_only(
                question="CQ dropped 6%",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )
        assert exc_info.value.stage == "DISPATCH"

    def test_empty_llm_response_raises_stage_error(self):
        """LLM returning empty string -> StageError because JSON extraction fails.

        An empty string is not valid JSON, so extract_json() raises LLMParseError,
        which gets wrapped in StageError at the HYPOTHESIZE stage.
        """
        def empty_response_llm(prompt: str, system: str, max_tokens: int) -> str:
            return ""

        orch = SearchMetricOrchestrator(llm_callable=empty_response_llm)
        with pytest.raises(StageError) as exc_info:
            orch.run_pipeline_only(
                question="CQ dropped",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )
        assert exc_info.value.stage == "HYPOTHESIZE"

    def test_orchestrator_error_catches_all_pipeline_errors(self):
        """OrchestratorError should catch StageError, LLMError, LLMParseError, LLMAPIError.

        This verifies the error hierarchy works as expected: a broad
        `except OrchestratorError` catches any pipeline failure, regardless
        of the specific error subtype.
        """
        # StageError from bad JSON at HYPOTHESIZE
        def bad_json_llm(prompt: str, system: str, max_tokens: int) -> str:
            return "not json"

        orch = SearchMetricOrchestrator(llm_callable=bad_json_llm)
        with pytest.raises(OrchestratorError):
            orch.run_pipeline_only(
                question="CQ dropped",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )

        # LLMAPIError propagated from LLM callable
        def api_failing_llm(prompt: str, system: str, max_tokens: int) -> str:
            raise LLMAPIError("Service unavailable", status_code=503)

        orch2 = SearchMetricOrchestrator(llm_callable=api_failing_llm)
        with pytest.raises(OrchestratorError):
            orch2.run(
                question="CQ dropped",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )

        # LLMParseError is a subtype of LLMError which is a subtype of OrchestratorError
        with pytest.raises(OrchestratorError):
            raise LLMParseError("bad parse", raw_response="junk")

        # Direct LLMError
        with pytest.raises(OrchestratorError):
            raise LLMError("generic llm error")


# ---------------------------------------------------------------------------
# Integration Tests — Retry Logic (Task 12)
# ---------------------------------------------------------------------------


class TestRetryIntegration:
    """Test SYNTHESIZE retry gate integration.

    SYNTHESIZE uses a RETRY(1) then SOFT gate pattern:
    - First attempt: validate the LLM output
    - If validation fails: retry once with violations appended to prompt
    - If second attempt also fails: continue with best-effort + completeness_warnings

    These tests verify all three paths.
    """

    def test_synthesize_retry_succeeds_on_second_attempt(self):
        """Mock LLM returns incomplete report first, complete second -> should succeed.

        This is the happy retry path: the LLM's first attempt is missing
        mandatory sections, but the retry (with violation feedback) produces
        a complete report.
        """
        synth_call_count = {"n": 0}

        def retry_success_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Returns incomplete report on first SYNTHESIZE call, complete on second."""
            if "final" in system.lower() and "investigation report" in system.lower():
                synth_call_count["n"] += 1
                if synth_call_count["n"] == 1:
                    # First attempt: empty mandatory sections -> triggers retry
                    return json.dumps({
                        "tldr": "CQ dropped.",
                        "confidence_grade": "Medium",
                        "severity": "P1",
                        "root_cause": "",
                        "dimensional_breakdown": "",
                        "hypothesis_and_evidence": "",
                        "validation_summary": "",
                        "recommended_actions": [],
                        "upgrade_condition": "",
                        "completeness_warnings": [],
                    })
                else:
                    # Retry: return complete report
                    return _make_valid_synthesis_json()
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=retry_success_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped 6%",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should complete successfully
        assert result["status"] == "complete"
        assert "SYNTHESIZE" in result["stages_completed"]
        # LLM should have been called twice for SYNTHESIZE
        assert synth_call_count["n"] == 2
        # Final report should have non-empty mandatory sections
        assert len(result["synthesis"]["root_cause"]) > 0
        assert len(result["synthesis"]["dimensional_breakdown"]) > 0

    def test_synthesize_double_failure_produces_completeness_warnings(self):
        """Mock LLM returns bad reports both times -> soft fallback with warnings.

        When both attempts fail validation, the pipeline continues with the
        best-effort report but adds completeness_warnings so the reader knows
        the report has known deficiencies.
        """
        def always_bad_synthesis_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Always returns incomplete SynthesisReport for SYNTHESIZE."""
            if "final" in system.lower() and "investigation report" in system.lower():
                return json.dumps({
                    "tldr": "CQ dropped.",
                    "confidence_grade": "Medium",
                    "severity": "P1",
                    "root_cause": "",  # empty -> violation
                    "dimensional_breakdown": "",  # empty -> violation
                    "hypothesis_and_evidence": "",  # empty -> violation
                    "validation_summary": "",  # empty -> violation
                    "recommended_actions": [],
                    "upgrade_condition": "",
                    "completeness_warnings": [],
                })
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=always_bad_synthesis_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        # Pipeline should still complete (SOFT fallback)
        assert result["status"] == "complete"
        # Completeness warnings should document the unresolved violations
        warnings = result["synthesis"]["completeness_warnings"]
        assert len(warnings) > 0
        # Each warning should reference SEAM VIOLATION
        assert any("SEAM VIOLATION" in w for w in warnings)

    def test_retry_prompt_includes_violation_messages(self):
        """The retry prompt should include the violation messages from first attempt.

        This is how the LLM "learns" from its mistake: the retry prompt appends
        the specific violations, telling the LLM exactly what to fix.
        """
        captured_synth_prompts = []
        synth_call_count = {"n": 0}

        def capturing_synth_llm(prompt: str, system: str, max_tokens: int) -> str:
            """Captures SYNTHESIZE prompts to verify retry includes violations."""
            if "final" in system.lower() and "investigation report" in system.lower():
                synth_call_count["n"] += 1
                captured_synth_prompts.append(prompt)
                if synth_call_count["n"] == 1:
                    # First attempt: missing sections
                    return json.dumps({
                        "tldr": "", "confidence_grade": "", "severity": "",
                        "root_cause": "", "dimensional_breakdown": "",
                        "hypothesis_and_evidence": "", "validation_summary": "",
                        "recommended_actions": [], "upgrade_condition": "",
                        "completeness_warnings": [],
                    })
                else:
                    return _make_valid_synthesis_json()
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=capturing_synth_llm)
        orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        # Two SYNTHESIZE calls: original + retry
        assert len(captured_synth_prompts) == 2

        # The retry prompt (second call) should include violation feedback
        retry_prompt = captured_synth_prompts[1]
        # The retry prompt appends "issues that MUST be fixed"
        assert "MUST be fixed" in retry_prompt
        # Should reference specific violations from first attempt
        assert "previous response" in retry_prompt.lower()


# ---------------------------------------------------------------------------
# Integration Tests — Transient vs Permanent Errors (Task 12)
# ---------------------------------------------------------------------------


class TestTransientVsPermanentErrors:
    """Test _call_with_retry handling of transient vs permanent errors.

    Transient errors (rate limits, server errors) should be retried with
    exponential backoff. Permanent errors (auth failures, bad requests)
    should fail immediately — no point wasting time retrying.

    IMPORTANT: _call_with_retry re-raises LLMAPIError immediately (it's
    already classified). The retry logic only kicks in for raw exceptions
    that get classified via _classify_api_error. So these tests use raw
    Exception subclasses with special names to trigger classification.
    """

    def test_transient_error_is_retried(self):
        """LLMAPIError with is_transient=True should be retried by _call_with_retry.

        We test this indirectly: a raw TimeoutError gets classified as transient
        by _classify_api_error, and _call_with_retry retries it.
        """
        from harness.llm import _call_with_retry

        call_count = {"n": 0}

        # Create a custom exception with "Timeout" in the name so
        # _classify_api_error classifies it as transient
        class APITimeoutError(Exception):
            """Simulates an API timeout error (transient)."""
            pass

        def flaky_call() -> str:
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise APITimeoutError("Request timed out")
            return "success"

        # Should succeed on third attempt
        result = _call_with_retry(flaky_call, max_attempts=3, base_delay=0.01)
        assert result == "success"
        assert call_count["n"] == 3  # tried 3 times

    def test_permanent_error_fails_immediately(self):
        """LLMAPIError with is_transient=False should fail immediately, no retries.

        A permanent error (e.g., 401 auth failure) means the request is
        fundamentally broken. Retrying wastes time.
        """
        from harness.llm import _call_with_retry

        call_count = {"n": 0}

        # Create a custom exception WITHOUT "Timeout" or "Connection" in the name.
        # _classify_api_error will classify it as permanent (status_code=None,
        # unknown exception type -> permanent).
        class AuthenticationError(Exception):
            """Simulates an auth error (permanent)."""
            pass

        def always_fail() -> str:
            call_count["n"] += 1
            raise AuthenticationError("Invalid API key")

        with pytest.raises(LLMAPIError) as exc_info:
            _call_with_retry(always_fail, max_attempts=3, base_delay=0.01)

        # Should have failed on the FIRST attempt (no retries for permanent errors)
        assert call_count["n"] == 1
        assert exc_info.value.is_transient is False

    def test_permanent_error_does_not_trigger_retries(self):
        """Verify that permanent errors exit the retry loop immediately.

        Even with max_attempts=5, a permanent error should only call once.
        """
        from harness.llm import _call_with_retry

        call_count = {"n": 0}

        class BadRequestError(Exception):
            """Simulates a 400 bad request (permanent)."""
            pass

        def bad_request() -> str:
            call_count["n"] += 1
            raise BadRequestError("Malformed request body")

        with pytest.raises(LLMAPIError):
            _call_with_retry(bad_request, max_attempts=5, base_delay=0.01)

        # Only 1 call — permanent errors don't retry
        assert call_count["n"] == 1

    def test_already_classified_llm_api_error_re_raises(self):
        """If call_fn raises an already-classified LLMAPIError, it re-raises immediately.

        This covers the path at line 231-232 of llm.py: LLMAPIError is caught
        and re-raised without going through _classify_api_error.
        """
        from harness.llm import _call_with_retry

        call_count = {"n": 0}

        def raises_classified_error() -> str:
            call_count["n"] += 1
            raise LLMAPIError("Already classified", is_transient=True, status_code=429)

        with pytest.raises(LLMAPIError) as exc_info:
            _call_with_retry(raises_classified_error, max_attempts=3, base_delay=0.01)

        # Should have been called only once — already-classified errors re-raise immediately
        assert call_count["n"] == 1
        assert exc_info.value.is_transient is True
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Integration Tests — IC9 Invisible Decisions End-to-End (Task 12)
# ---------------------------------------------------------------------------


class TestIC9InvisibleDecisionsEndToEnd:
    """Verify ALL 4 IC9 Invisible Decisions are traced in a full pipeline run.

    IC9 audit found 4 "Invisible Decisions" — choices the system makes that
    were previously unrecorded. Each must now have a trace span with the
    correct stage, swimlane, and decision field.

    The 4 decisions are:
    1. metric_direction (UNDERSTAND) — what direction did the metric move?
    2. hypothesis_inclusion (HYPOTHESIZE) — what hypotheses were included/excluded?
    3. context_construction (DISPATCH) — what context was given to investigators?
    4. narrative_selection (SYNTHESIZE) — what narrative framing was chosen?
    """

    def test_all_four_decisions_present_in_trace(self):
        """Run full pipeline and verify all 4 IC9 decisions appear in trace spans."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        spans = result["trace"].get("spans", [])
        decisions = [s.get("decision") for s in spans]

        assert "metric_direction" in decisions,    "IC9 #1 missing: metric_direction"
        assert "hypothesis_inclusion" in decisions, "IC9 #2 missing: hypothesis_inclusion"
        assert "context_construction" in decisions, "IC9 #3 missing: context_construction"
        assert "narrative_selection" in decisions,  "IC9 #4 missing: narrative_selection"

    def test_metric_direction_span_correct_stage_and_swimlane(self):
        """IC9 #1: metric_direction should be in UNDERSTAND stage, deterministic swimlane."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        spans = result["trace"]["spans"]
        md_spans = [s for s in spans if s.get("decision") == "metric_direction"]
        assert len(md_spans) >= 1
        span = md_spans[0]
        assert span["stage"] == "UNDERSTAND"
        # metric_direction is set by deterministic code (decomposition output),
        # so it should be in the deterministic swimlane with code_enforced=True
        assert span["swimlane"] == "deterministic"
        assert span["code_enforced"] is True

    def test_hypothesis_inclusion_span_correct_stage_and_swimlane(self):
        """IC9 #2: hypothesis_inclusion should be in HYPOTHESIZE, llm_generated swimlane."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        spans = result["trace"]["spans"]
        hi_spans = [s for s in spans if s.get("decision") == "hypothesis_inclusion"]
        assert len(hi_spans) == 1
        span = hi_spans[0]
        assert span["stage"] == "HYPOTHESIZE"
        assert span["swimlane"] == "llm_generated"
        assert span["code_enforced"] is False
        # Value should have included/excluded archetypes
        assert "included" in span["value"]
        assert "excluded" in span["value"]

    def test_context_construction_span_correct_stage_and_swimlane(self):
        """IC9 #3: context_construction should be in DISPATCH, llm_generated swimlane."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        spans = result["trace"]["spans"]
        cc_spans = [s for s in spans if s.get("decision") == "context_construction"]
        assert len(cc_spans) == 1
        span = cc_spans[0]
        assert span["stage"] == "DISPATCH"
        assert span["swimlane"] == "llm_generated"
        assert span["code_enforced"] is False
        # Value should record how many hypotheses were investigated
        assert "hypotheses_investigated" in span["value"]

    def test_narrative_selection_span_correct_stage_and_swimlane(self):
        """IC9 #4: narrative_selection should be in SYNTHESIZE, llm_generated swimlane."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        spans = result["trace"]["spans"]
        ns_spans = [s for s in spans if s.get("decision") == "narrative_selection"]
        assert len(ns_spans) == 1
        span = ns_spans[0]
        assert span["stage"] == "SYNTHESIZE"
        assert span["swimlane"] == "llm_generated"
        assert span["code_enforced"] is False
        # Value should include report metadata
        assert "confidence_grade" in span["value"]
        assert "severity" in span["value"]

    def test_trace_has_seam_validation_for_all_four_stages(self):
        """Seam validation records should exist for all 4 stages."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        seam_validations = result["trace"].get("seam_validations", [])
        seam_stages = set(s["stage"] for s in seam_validations)

        assert "UNDERSTAND" in seam_stages,  "Missing seam validation for UNDERSTAND"
        assert "HYPOTHESIZE" in seam_stages, "Missing seam validation for HYPOTHESIZE"
        assert "DISPATCH" in seam_stages,    "Missing seam validation for DISPATCH"
        assert "SYNTHESIZE" in seam_stages,  "Missing seam validation for SYNTHESIZE"

    def test_invisible_decisions_in_trace_summary(self):
        """All 4 IC9 decisions should appear in the trace summary's invisible_decisions list."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        invisible = result["trace"].get("summary", {}).get(
            "invisible_decisions_traced", []
        )
        expected_decisions = [
            "metric_direction",
            "hypothesis_inclusion",
            "context_construction",
            "narrative_selection",
        ]
        for decision in expected_decisions:
            assert decision in invisible, (
                f"IC9 decision '{decision}' not in trace summary"
            )


# ---------------------------------------------------------------------------
# Integration Tests — Blocked Report Generation (Task 12)
# ---------------------------------------------------------------------------


class TestBlockedReportGeneration:
    """Test that bad data quality produces a blocked report and skips LLM stages.

    When check_data_quality returns "fail", the pipeline should:
    1. Return a report with status="blocked"
    2. Include a reason explaining what went wrong
    3. Include remediation guidance
    4. NOT call HYPOTHESIZE, DISPATCH, or SYNTHESIZE
    """

    def test_bad_data_quality_produces_blocked_report(self):
        """Data completeness < 96% -> blocked report."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "blocked"

    def test_blocked_report_has_required_fields(self):
        """Blocked report should contain status, reason, and remediation."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert result["status"] == "blocked"
        assert "blocked_reason" in result
        assert len(result["blocked_reason"]) > 0
        assert "remediation" in result
        assert len(result["remediation"]) > 0

    def test_blocked_report_has_remediation_guidance(self):
        """Remediation should mention actionable fixes (e.g., completeness threshold)."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        remediation = result["remediation"].lower()
        # Should mention data completeness or freshness as the fix
        assert "completeness" in remediation or "data quality" in remediation

    def test_llm_not_called_when_blocked(self):
        """HYPOTHESIZE, DISPATCH, SYNTHESIZE should NOT be called when blocked.

        This is a cost check: if data quality fails, we should not waste
        LLM API calls (and money) on stages that can't produce trustworthy results.
        """
        llm_call_count = {"n": 0}

        def counting_llm(prompt: str, system: str, max_tokens: int) -> str:
            llm_call_count["n"] += 1
            return _dummy_llm(prompt, system, max_tokens)

        orch = SearchMetricOrchestrator(llm_callable=counting_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert result["status"] == "blocked"
        # The LLM should NEVER have been called
        assert llm_call_count["n"] == 0, (
            f"LLM was called {llm_call_count['n']} times for a blocked pipeline"
        )

    def test_blocked_report_stages_completed_is_empty(self):
        """When blocked at UNDERSTAND, stages_completed should be empty."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert result["stages_completed"] == []

    def test_blocked_report_includes_trace(self):
        """Even blocked reports should include a trace for debugging."""
        orch = SearchMetricOrchestrator(llm_callable=_dummy_llm)
        result = orch.run_pipeline_only(
            question="CQ dropped",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
        )
        assert "trace" in result
        assert "trace_id" in result["trace"]


# ---------------------------------------------------------------------------
# Integration Tests — Pipeline Configuration (Task 12)
# ---------------------------------------------------------------------------


class TestPipelineConfiguration:
    """Test orchestrator configuration handling.

    The orchestrator accepts optional config overrides for max_retries,
    timeout_seconds, and agent callables. These tests verify that
    configuration is applied correctly and missing LLM callable is handled.
    """

    def test_custom_config_overrides_applied(self):
        """Custom max_retries and timeout should override defaults."""
        custom_config = {"max_retries": 5, "timeout_seconds": 120}
        orch = SearchMetricOrchestrator(
            llm_callable=_dummy_llm,
            config=custom_config,
        )
        assert orch._config["max_retries"] == 5
        assert orch._config["timeout_seconds"] == 120

    def test_default_config_preserved_for_unset_keys(self):
        """Keys not in custom config should keep their default values."""
        orch = SearchMetricOrchestrator(
            llm_callable=_dummy_llm,
            config={"max_retries": 10},
        )
        assert orch._config["max_retries"] == 10
        # timeout_seconds should keep its default
        assert orch._config["timeout_seconds"] == 60

    def test_agent_callables_in_config_used_at_dispatch(self):
        """When config has 'agents', DISPATCH should use them instead of LLM."""
        agent_called = {"count": 0}

        def mock_agent(diagnosis_context: dict, hypothesis: dict):
            """Mock agent callable for DISPATCH."""
            agent_called["count"] += 1
            return {
                "agent": "mock_agent",
                "ran": True,
                "verdict": "confirmed",
                "reason": "Mock agent confirmed the hypothesis",
                "queries": [],
                "evidence": [{"metric": "click_quality", "value": 0.245}],
                "cost": {"queries": 0, "seconds": 0.0},
            }

        orch = SearchMetricOrchestrator(
            llm_callable=_dummy_llm,
            config={"agents": [mock_agent]},
        )
        result = orch.run_pipeline_only(
            question="CQ dropped 6%",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )
        assert result["status"] == "complete"
        # Agent should have been called (once per hypothesis)
        assert agent_called["count"] >= 1

    def test_missing_llm_callable_raises_error(self):
        """Passing None as llm_callable should raise an error when LLM is needed.

        The LLM is not needed for UNDERSTAND (deterministic), but HYPOTHESIZE
        calls self._llm(), which will fail if it's None.
        """
        orch = SearchMetricOrchestrator(llm_callable=None)
        with pytest.raises(TypeError):
            orch.run_pipeline_only(
                question="CQ dropped",
                rows=_make_good_rows(),
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
            )


# ===========================================================================
# run() Integration Tests (full 5-stage pipeline with QUESTION_PARSE)
# ===========================================================================

class TestRunIntegration:
    """Integration tests for the main pipeline entry point: run().

    These tests validate the end-to-end flow:
    question -> QUESTION_PARSE -> mode selection -> pipeline -> result.

    run() was renamed from run_v2() in the stage extraction refactor.
    """

    def _make_mock_llm(self):
        """Create a mock LLM callable that returns valid JSON for all stages."""
        call_count = [0]

        def mock_llm(prompt, system="", max_tokens=4096):
            call_count[0] += 1
            # HYPOTHESIZE calls come first
            if "hypothes" in system.lower() or "hypothes" in prompt.lower():
                return _make_valid_hypothesis_json()
            # DISPATCH calls — return a finding for each hypothesis
            if "investigat" in system.lower() or "evidence" in prompt.lower():
                hyp_id = "hyp_001"
                # Try to extract hypothesis_id from the prompt
                if "hyp_002" in prompt:
                    hyp_id = "hyp_002"
                elif "hyp_003" in prompt:
                    hyp_id = "hyp_003"
                return _make_valid_finding_json(hyp_id)
            # SYNTHESIZE calls
            return _make_valid_synthesis_json()

        return mock_llm

    def test_run_simple_mode_returns_directly(self):
        """Simple mode should skip the pipeline and return immediately.

        When the question is a simple lookup (e.g., "what is click quality?"),
        run should parse it, select 'simple' mode, and return without
        running any LLM calls.
        """
        orch = SearchMetricOrchestrator(llm_callable=None)  # No LLM needed
        result = orch.run(
            question="What is the click quality formula?",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )

        assert result["status"] == "complete"
        assert result["mode"] == "simple"
        assert "question_brief" in result
        assert result["question_brief"]["question_type"] == "adhoc"
        assert result["stages_completed"] == ["QUESTION_PARSE"]
        assert "trace" in result

    def test_run_medium_mode_runs_full_pipeline(self):
        """Medium mode should run the full 4-stage pipeline sequentially.

        A question like "Click Quality dropped 6% WoW" should be classified
        as 'sev' type, selected as 'medium' mode, and run through all 4 stages.
        """
        mock_llm = self._make_mock_llm()
        orch = SearchMetricOrchestrator(llm_callable=mock_llm)
        result = orch.run(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        assert result["status"] == "complete"
        assert result["mode"] in ("medium", "complex")
        assert "question_brief" in result
        assert "mode_decision" in result
        # All 5 stages should be completed (QUESTION_PARSE + 4 pipeline stages)
        assert "QUESTION_PARSE" in result["stages_completed"]
        assert "UNDERSTAND" in result["stages_completed"]
        assert "SYNTHESIZE" in result["stages_completed"]
        # Pipeline results should be present
        assert "understand_result" in result
        assert "hypothesize_result" in result
        assert "dispatch_result" in result
        assert "synthesis" in result
        assert "trace" in result

    def test_run_complex_mode_override(self):
        """Overriding mode to 'complex' should use parallel dispatch."""
        mock_llm = self._make_mock_llm()
        orch = SearchMetricOrchestrator(llm_callable=mock_llm)
        result = orch.run(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
            override_mode="complex",
        )

        assert result["status"] == "complete"
        assert result["mode"] == "complex"
        assert "QUESTION_PARSE" in result["stages_completed"]
        assert "DISPATCH" in result["stages_completed"]

    def test_run_bad_data_returns_blocked(self):
        """Bad data quality should block the pipeline at UNDERSTAND."""
        mock_llm = self._make_mock_llm()
        orch = SearchMetricOrchestrator(llm_callable=mock_llm)
        result = orch.run(
            question="Click Quality dropped 6% WoW",
            rows=_make_bad_quality_rows(),
            metric_field="click_quality_value",
            dimensions=["tenant_tier"],
        )

        assert result["status"] == "blocked"
        assert "trace" in result

    def test_run_question_brief_has_correct_fields(self):
        """The question_brief should have the expected fields from parsing."""
        orch = SearchMetricOrchestrator(llm_callable=None)
        result = orch.run(
            question="What is the click quality formula?",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )

        brief = result["question_brief"]
        assert "question_type" in brief
        assert "raw_question" in brief
        assert "metric_hints" in brief

    def test_run_mode_decision_has_confidence(self):
        """The mode_decision should include confidence and reasoning."""
        mock_llm = self._make_mock_llm()
        orch = SearchMetricOrchestrator(llm_callable=mock_llm)
        result = orch.run(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )

        decision = result["mode_decision"]
        assert "mode" in decision
        assert "confidence" in decision

    def test_run_core_tool_crash_returns_stage_error(self):
        """If core/ tools crash on bad input, stage_understand wraps in StageError.

        This tests gap 4a: unexpected errors from core/ tools should be caught
        and wrapped in StageError rather than propagating as raw exceptions.

        We test stage_understand directly with rows=None to force a crash
        that the try/except should catch. (run is too defensive at the
        data quality layer to reach the crash path with normal bad data.)
        """
        from harness.stages import stage_understand
        from trace.collector import InvestigationTrace
        trace = InvestigationTrace(question="test")

        # None rows will crash check_data_quality (TypeError).
        # The try/except in stage_understand should catch this.
        with pytest.raises(StageError) as exc_info:
            stage_understand(
                question="Click Quality dropped 6% WoW",
                rows=None,
                metric_field="click_quality_value",
                dimensions=["tenant_tier"],
                trace=trace,
            )

        assert exc_info.value.stage == "UNDERSTAND"
        assert "Core tool error" in exc_info.value.violations[0]

    def test_run_thread_safety_no_instance_state(self):
        """run() should not store per-invocation state on self.

        This verifies gap 8: mode and question_type should be passed through
        the method chain as parameters, not stored as self._current_mode.
        """
        mock_llm = self._make_mock_llm()
        orch = SearchMetricOrchestrator(llm_callable=mock_llm)

        # Run a medium-mode investigation
        orch.run(
            question="Click Quality dropped 6% WoW",
            rows=_make_good_rows(),
            metric_field="click_quality_value",
        )

        # Verify no per-invocation state was stored on the instance
        assert not hasattr(orch, "_current_mode")
        assert not hasattr(orch, "_current_question_type")


class TestOrchestratorDomainWiring:
    """Verify orchestrator accepts and passes domain to stages."""

    def test_accepts_domain_parameter(self):
        import inspect
        from harness.orchestrator import SearchMetricOrchestrator
        sig = inspect.signature(SearchMetricOrchestrator.__init__)
        assert "domain" in sig.parameters

    def test_domain_defaults_to_none(self):
        """Without domain param, orchestrator creates SearchMetricsDomain internally."""
        import inspect
        from harness.orchestrator import SearchMetricOrchestrator
        sig = inspect.signature(SearchMetricOrchestrator.__init__)
        assert sig.parameters["domain"].default is None

    def test_stores_domain_instance(self):
        """Orchestrator should store the domain for passing to stages."""
        from harness.orchestrator import SearchMetricOrchestrator
        from domains.search_metrics import SearchMetricsDomain

        domain = SearchMetricsDomain()
        orch = SearchMetricOrchestrator(
            llm_callable=lambda p, s, m: "{}",
            domain=domain,
        )
        assert orch._domain is domain

    def test_default_domain_is_search_metrics(self):
        """When no domain is passed, orchestrator creates SearchMetricsDomain."""
        from harness.orchestrator import SearchMetricOrchestrator
        from domains.search_metrics import SearchMetricsDomain

        orch = SearchMetricOrchestrator(llm_callable=lambda p, s, m: "{}")
        assert isinstance(orch._domain, SearchMetricsDomain)
        assert orch._domain.name == "search_metrics"
