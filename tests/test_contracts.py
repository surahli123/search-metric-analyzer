"""Tests for the contracts module — seam validation, business rules, and CLI.

Covers:
- SeamViolation exception
- validate_seam() with passing/failing data for each stage
- Gate tier behavior: hard (raises), soft (returns), retry (raises)
- Trace integration: emit_seam called when trace provided
- All individual business rules from each stage
- CLI interface (python -m contracts.seam_validator)
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

from contracts.seam_validator import (
    # Core function and exception
    validate_seam,
    SeamViolation,
    GATE_TIERS,
    # UNDERSTAND rules
    rule_data_quality_not_failed,
    rule_metric_direction_set,
    # HYPOTHESIZE rules
    rule_min_three_hypotheses,
    rule_all_have_confirms_if,
    rule_has_contrarian_hypothesis,
    rule_expected_magnitude_present,
    rule_hypotheses_consistent_with_co_movement,
    rule_mix_shift_considered_when_detected,
    # DISPATCH rules
    rule_each_finding_has_evidence,
    rule_narrative_data_coherence,
    # SYNTHESIZE rules
    rule_all_mandatory_sections_present,
    rule_effect_size_proportionality,
    rule_upgrade_condition_stated,
)
from trace.collector import InvestigationTrace


# =============================================================================
# Fixtures — reusable stage output dicts
# =============================================================================

# The project root, needed for CLI tests
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def valid_understand_result():
    """A passing UNDERSTAND stage output with all required fields."""
    return {
        "question": "CQ dropped 6.2%",
        "metric": "click_quality",
        "direction": "down",
        "severity": "P1",
        "data_quality_status": "pass",
        "metric_direction": "down",
        "co_movement_pattern": {
            "pattern_name": "ranking_regression",
            "match_score": 0.85,
        },
        "mix_shift_result": {
            "detected": False,
            "contribution_pct": 0.05,
        },
    }


@pytest.fixture
def valid_hypothesis_set():
    """A passing HYPOTHESIZE stage output with 3 hypotheses including a contrarian."""
    return {
        "hypotheses": [
            {
                "hypothesis_id": "h1",
                "archetype": "ranking_regression",
                "priority": 1,
                "confirms_if": ["NDCG drops in A/B test"],
                "rejects_if": ["NDCG stable"],
                "expected_magnitude": "CQ drop of 3-6%",
                "source": "data_driven",
                "is_contrarian": False,
            },
            {
                "hypothesis_id": "h2",
                "archetype": "connector_degradation",
                "priority": 2,
                "confirms_if": ["connector error rate > 5%"],
                "rejects_if": ["connector healthy"],
                "expected_magnitude": "CQ drop of 1-3%",
                "source": "playbook",
                "is_contrarian": False,
            },
            {
                "hypothesis_id": "h3",
                "archetype": "false_alarm",
                "priority": 3,
                "confirms_if": ["within normal variance"],
                "rejects_if": ["exceeds 2 sigma"],
                "expected_magnitude": "CQ stable within noise",
                "source": "novel",
                "is_contrarian": True,
            },
        ],
        "exclusions": [],
        "investigation_context": "CQ dropped 6.2% WoW",
    }


@pytest.fixture
def valid_finding_set():
    """A passing DISPATCH stage output with evidence-backed findings."""
    return {
        "findings": [
            {
                "agent_name": "ranking_investigator",
                "hypothesis_id": "h1",
                "verdict": "confirmed",
                "confidence": 0.85,
                "evidence": [{"metric": "ndcg", "direction": "down", "delta": -0.04}],
                "narrative": "NDCG dropped 4% after the ranking model update",
                "adjacent_observations": [],
            },
        ],
        "context_construction_trace": "Full UNDERSTAND context provided to each agent",
    }


@pytest.fixture
def valid_synthesis_report():
    """A passing SYNTHESIZE stage output with all 7 mandatory sections."""
    return {
        "tldr": "CQ dropped 6.2% due to a ranking model regression.",
        "confidence_grade": "High",
        "severity": "P1",
        "root_cause": "Ranking model v2.3 introduced a position bias regression.",
        "dimensional_breakdown": "Standard tier affected most, premium tier stable.",
        "hypothesis_and_evidence": "Ranking regression confirmed via NDCG drop.",
        "validation_summary": "Cross-checked with A/B holdback group.",
        "recommended_actions": [
            {"action": "Rollback ranking model", "owner": "Search Eng", "priority": "immediate", "rationale": "Clear regression"},
        ],
        "upgrade_condition": "Would upgrade to High if rollback confirms recovery",
        "investigation_id": "inv_test123",
        "completeness_warnings": [],
    }


# =============================================================================
# TestSeamViolationException
# =============================================================================

class TestSeamViolationException:
    """Tests for the SeamViolation exception class."""

    def test_stores_stage_violations_tier(self):
        """SeamViolation should store stage, violations, and tier for error handling."""
        exc = SeamViolation("UNDERSTAND", ["bad data"], "hard")
        assert exc.stage == "UNDERSTAND"
        assert exc.violations == ["bad data"]
        assert exc.tier == "hard"

    def test_message_includes_all_violations(self):
        """String representation should include all violation messages."""
        exc = SeamViolation("HYPOTHESIZE", ["too few", "no contrarian"], "soft")
        msg = str(exc)
        assert "HYPOTHESIZE" in msg
        assert "too few" in msg
        assert "no contrarian" in msg


# =============================================================================
# TestValidateSeam — core validation with gate tiers
# =============================================================================

class TestValidateSeam:
    """Tests for validate_seam() — the central enforcement function."""

    # -- Passing validation ---------------------------------------------------

    def test_understand_passes_with_valid_data(self, valid_understand_result):
        """Valid UNDERSTAND output should pass all rules."""
        result = validate_seam(valid_understand_result, "UNDERSTAND")
        assert result["passed"] is True
        assert result["violations"] == []
        assert result["tier"] == "hard"

    def test_hypothesize_passes_with_valid_data(self, valid_hypothesis_set, valid_understand_result):
        """Valid HYPOTHESIZE output should pass all rules."""
        result = validate_seam(
            valid_hypothesis_set, "HYPOTHESIZE",
            understand_result=valid_understand_result,
        )
        assert result["passed"] is True

    def test_dispatch_passes_with_valid_data(self, valid_finding_set):
        """Valid DISPATCH output should pass all rules."""
        result = validate_seam(valid_finding_set, "DISPATCH")
        assert result["passed"] is True

    def test_synthesize_passes_with_valid_data(self, valid_synthesis_report):
        """Valid SYNTHESIZE output should pass all rules."""
        result = validate_seam(valid_synthesis_report, "SYNTHESIZE")
        assert result["passed"] is True

    # -- Gate tier behavior ---------------------------------------------------

    def test_understand_hard_gate_raises_on_failure(self):
        """UNDERSTAND is a HARD gate — failure raises SeamViolation."""
        bad_data = {"data_quality_status": "fail", "metric_direction": "down"}
        with pytest.raises(SeamViolation) as exc_info:
            validate_seam(bad_data, "UNDERSTAND")
        assert exc_info.value.tier == "hard"
        assert exc_info.value.stage == "UNDERSTAND"

    def test_hypothesize_soft_gate_returns_on_failure(self):
        """HYPOTHESIZE is a SOFT gate — failure returns result, does not raise."""
        bad_data = {"hypotheses": []}  # No hypotheses
        result = validate_seam(bad_data, "HYPOTHESIZE")
        assert result["passed"] is False
        assert result["tier"] == "soft"
        assert len(result["violations"]) > 0

    def test_dispatch_soft_gate_returns_on_failure(self):
        """DISPATCH is a SOFT gate — failure returns result, does not raise."""
        bad_data = {
            "findings": [
                {"agent_name": "test", "hypothesis_id": "h1", "evidence": [], "narrative": "story"},
            ],
        }
        result = validate_seam(bad_data, "DISPATCH")
        assert result["passed"] is False
        assert result["tier"] == "soft"

    def test_synthesize_retry_gate_raises_on_failure(self):
        """SYNTHESIZE is a RETRY gate — failure raises SeamViolation for caller to retry."""
        bad_data = {"severity": "P1"}  # Missing most mandatory sections
        with pytest.raises(SeamViolation) as exc_info:
            validate_seam(bad_data, "SYNTHESIZE")
        assert exc_info.value.tier == "retry"

    # -- Trace integration ----------------------------------------------------

    def test_trace_emit_seam_called_on_pass(self, valid_understand_result):
        """When trace is provided, emit_seam() should be called on passing validation."""
        trace = InvestigationTrace(question="test")
        validate_seam(valid_understand_result, "UNDERSTAND", trace=trace)
        seam = trace.seam_for_stage("UNDERSTAND")
        assert seam is not None
        assert seam["passed"] is True
        assert seam["schema"] == "UnderstandResult"

    def test_trace_emit_seam_called_on_soft_failure(self):
        """Trace should record the seam even when a soft gate fails."""
        trace = InvestigationTrace(question="test")
        validate_seam({"hypotheses": []}, "HYPOTHESIZE", trace=trace)
        seam = trace.seam_for_stage("HYPOTHESIZE")
        assert seam is not None
        assert seam["passed"] is False
        assert seam["tier"] == "soft"

    def test_trace_emit_seam_called_on_hard_failure(self):
        """Trace should record the seam even when a hard gate raises."""
        trace = InvestigationTrace(question="test")
        with pytest.raises(SeamViolation):
            validate_seam(
                {"data_quality_status": "fail", "metric_direction": "down"},
                "UNDERSTAND",
                trace=trace,
            )
        # Seam should still be recorded before the exception
        seam = trace.seam_for_stage("UNDERSTAND")
        assert seam is not None
        assert seam["passed"] is False

    def test_trace_schema_names_correct(self, valid_understand_result, valid_hypothesis_set,
                                         valid_finding_set, valid_synthesis_report):
        """Each stage should emit the correct schema name in the seam."""
        expected = {
            "UNDERSTAND": ("UnderstandResult", valid_understand_result),
            "HYPOTHESIZE": ("HypothesisSet", valid_hypothesis_set),
            "DISPATCH": ("FindingSet", valid_finding_set),
            "SYNTHESIZE": ("SynthesisReport", valid_synthesis_report),
        }
        for stage, (schema, data) in expected.items():
            trace = InvestigationTrace(question="test")
            try:
                validate_seam(data, stage, trace=trace)
            except SeamViolation:
                pass  # Some may raise; we still check the seam
            seam = trace.seam_for_stage(stage)
            assert seam["schema"] == schema, f"Stage {stage} should emit schema {schema}"

    # -- Per-rule checks dict -------------------------------------------------

    def test_checks_dict_tracks_individual_rules(self, valid_understand_result):
        """The checks dict should have True/False for each rule name."""
        result = validate_seam(valid_understand_result, "UNDERSTAND")
        assert "rule_data_quality_not_failed" in result["checks"]
        assert "rule_metric_direction_set" in result["checks"]
        assert all(v is True for v in result["checks"].values())

    # -- Custom business rules ------------------------------------------------

    def test_custom_rules_override_defaults(self):
        """Passing business_rules should override the stage's default rules."""
        def always_fail(result, **kwargs):
            return "Always fails"

        result = validate_seam(
            {}, "HYPOTHESIZE",
            business_rules=[always_fail],
        )
        assert result["passed"] is False
        assert "Always fails" in result["violations"]

    # -- Unknown stage falls back to soft ------------------------------------

    def test_unknown_stage_defaults_to_soft(self):
        """An unregistered stage should default to soft tier with no rules."""
        result = validate_seam({}, "UNKNOWN_STAGE")
        assert result["passed"] is True
        assert result["tier"] == "soft"


# =============================================================================
# TestUnderstandRules
# =============================================================================

class TestUnderstandRules:
    """Tests for UNDERSTAND stage business rules."""

    # -- rule_data_quality_not_failed -----------------------------------------

    def test_data_quality_fail_returns_violation(self):
        """data_quality_status='fail' should block the investigation."""
        msg = rule_data_quality_not_failed({"data_quality_status": "fail"})
        assert msg is not None
        assert "FAILED" in msg

    def test_data_quality_pass_returns_none(self):
        """data_quality_status='pass' is the happy path."""
        assert rule_data_quality_not_failed({"data_quality_status": "pass"}) is None

    def test_data_quality_warn_returns_none(self):
        """data_quality_status='warn' is degraded but acceptable."""
        assert rule_data_quality_not_failed({"data_quality_status": "warn"}) is None

    def test_data_quality_missing_returns_none(self):
        """Missing data_quality_status should not trigger a failure (not 'fail')."""
        assert rule_data_quality_not_failed({}) is None

    # -- rule_metric_direction_set --------------------------------------------

    def test_metric_direction_empty_fails(self):
        """Empty metric_direction should fail — IC9 Invisible Decision must be explicit."""
        msg = rule_metric_direction_set({"metric_direction": ""})
        assert msg is not None
        assert "IC9" in msg

    def test_metric_direction_missing_fails(self):
        """Missing metric_direction should fail."""
        msg = rule_metric_direction_set({})
        assert msg is not None

    def test_metric_direction_invalid_value_fails(self):
        """metric_direction must be one of up/down/stable."""
        msg = rule_metric_direction_set({"metric_direction": "sideways"})
        assert msg is not None
        assert "sideways" in msg

    def test_metric_direction_up_passes(self):
        """'up' is a valid metric direction."""
        assert rule_metric_direction_set({"metric_direction": "up"}) is None

    def test_metric_direction_down_passes(self):
        """'down' is a valid metric direction."""
        assert rule_metric_direction_set({"metric_direction": "down"}) is None

    def test_metric_direction_stable_passes(self):
        """'stable' is a valid metric direction."""
        assert rule_metric_direction_set({"metric_direction": "stable"}) is None


# =============================================================================
# TestHypothesizeRules
# =============================================================================

class TestHypothesizeRules:
    """Tests for HYPOTHESIZE stage business rules."""

    # -- rule_min_three_hypotheses --------------------------------------------

    def test_zero_hypotheses_fails(self):
        """0 hypotheses should fail — need minimum 3 to avoid tunnel vision."""
        msg = rule_min_three_hypotheses({"hypotheses": []})
        assert msg is not None
        assert "0" in msg

    def test_one_hypothesis_fails(self):
        """1 hypothesis should fail."""
        msg = rule_min_three_hypotheses({"hypotheses": [{"id": "h1"}]})
        assert msg is not None
        assert "1" in msg

    def test_two_hypotheses_fails(self):
        """2 hypotheses should fail."""
        msg = rule_min_three_hypotheses({"hypotheses": [{"id": "h1"}, {"id": "h2"}]})
        assert msg is not None
        assert "2" in msg

    def test_three_hypotheses_passes(self):
        """3 hypotheses is the minimum — should pass."""
        assert rule_min_three_hypotheses({"hypotheses": [
            {"id": "h1"}, {"id": "h2"}, {"id": "h3"}
        ]}) is None

    def test_five_hypotheses_passes(self):
        """More than 3 hypotheses should also pass."""
        assert rule_min_three_hypotheses({"hypotheses": [
            {"id": f"h{i}"} for i in range(5)
        ]}) is None

    def test_missing_hypotheses_key_fails(self):
        """Missing 'hypotheses' key should be treated as 0 hypotheses."""
        msg = rule_min_three_hypotheses({})
        assert msg is not None
        assert "0" in msg

    # -- rule_all_have_confirms_if --------------------------------------------

    def test_empty_confirms_if_fails(self):
        """Hypothesis with empty confirms_if should fail — can't investigate without criteria."""
        msg = rule_all_have_confirms_if({
            "hypotheses": [
                {"hypothesis_id": "h1", "confirms_if": ["evidence"]},
                {"hypothesis_id": "h2", "confirms_if": []},
            ]
        })
        assert msg is not None
        assert "h2" in msg

    def test_missing_confirms_if_fails(self):
        """Hypothesis without confirms_if key should fail."""
        msg = rule_all_have_confirms_if({
            "hypotheses": [{"hypothesis_id": "h1"}]
        })
        assert msg is not None

    def test_all_have_confirms_if_passes(self):
        """All hypotheses with non-empty confirms_if should pass."""
        assert rule_all_have_confirms_if({
            "hypotheses": [
                {"hypothesis_id": "h1", "confirms_if": ["a"]},
                {"hypothesis_id": "h2", "confirms_if": ["b"]},
            ]
        }) is None

    # -- rule_has_contrarian_hypothesis ---------------------------------------

    def test_no_contrarian_fails(self):
        """Without any contrarian hypothesis, confirmation bias risk is too high."""
        msg = rule_has_contrarian_hypothesis({
            "hypotheses": [
                {"is_contrarian": False},
                {"is_contrarian": False},
                {"is_contrarian": False},
            ]
        })
        assert msg is not None
        assert "contrarian" in msg.lower()

    def test_one_contrarian_passes(self):
        """At least one contrarian hypothesis should pass."""
        assert rule_has_contrarian_hypothesis({
            "hypotheses": [
                {"is_contrarian": False},
                {"is_contrarian": True},
                {"is_contrarian": False},
            ]
        }) is None

    def test_no_is_contrarian_field_fails(self):
        """Hypotheses without the is_contrarian field should fail (falsy)."""
        msg = rule_has_contrarian_hypothesis({
            "hypotheses": [{"archetype": "a"}, {"archetype": "b"}, {"archetype": "c"}]
        })
        assert msg is not None

    # -- rule_expected_magnitude_present --------------------------------------

    def test_missing_expected_magnitude_fails(self):
        """Hypothesis without expected_magnitude should fail."""
        msg = rule_expected_magnitude_present({
            "hypotheses": [
                {"hypothesis_id": "h1", "expected_magnitude": "CQ drop 3-6%"},
                {"hypothesis_id": "h2"},  # missing
            ]
        })
        assert msg is not None
        assert "h2" in msg

    def test_empty_expected_magnitude_fails(self):
        """Empty string expected_magnitude should fail."""
        msg = rule_expected_magnitude_present({
            "hypotheses": [{"hypothesis_id": "h1", "expected_magnitude": ""}]
        })
        assert msg is not None

    def test_all_have_expected_magnitude_passes(self):
        """All hypotheses with expected_magnitude should pass."""
        assert rule_expected_magnitude_present({
            "hypotheses": [
                {"hypothesis_id": "h1", "expected_magnitude": "drop 3%"},
                {"hypothesis_id": "h2", "expected_magnitude": "stable"},
            ]
        }) is None

    # -- rule_hypotheses_consistent_with_co_movement --------------------------

    def test_ai_adoption_with_cq_degradation_not_contrarian_fails(self):
        """THE CRITICAL TEST: ai_adoption_expected + click_quality_degradation = must be contrarian.

        This is the 'AI adoption trap': AI answers work well -> users click less ->
        CQ drops -> team panics. But it's a POSITIVE signal. Flagging CQ degradation
        as anomalous when AI adoption explains it is the #1 false alarm pattern.
        """
        understand = {
            "co_movement_pattern": {
                "pattern_name": "ai_adoption_expected",
                "match_score": 0.9,
            }
        }
        result = {
            "hypotheses": [
                {
                    "hypothesis_id": "h1",
                    "archetype": "click_quality_degradation",
                    "is_contrarian": False,  # NOT marked contrarian
                },
            ]
        }
        msg = rule_hypotheses_consistent_with_co_movement(result, understand_result=understand)
        assert msg is not None
        assert "ai_adoption_expected" in msg
        assert "click_quality_degradation" in msg

    def test_ai_adoption_with_cq_degradation_contrarian_passes(self):
        """When CQ degradation is marked contrarian under AI adoption, it's acceptable."""
        understand = {
            "co_movement_pattern": {
                "pattern_name": "ai_adoption_expected",
                "match_score": 0.9,
            }
        }
        result = {
            "hypotheses": [
                {
                    "hypothesis_id": "h1",
                    "archetype": "click_quality_degradation",
                    "is_contrarian": True,
                },
            ]
        }
        assert rule_hypotheses_consistent_with_co_movement(
            result, understand_result=understand
        ) is None

    def test_different_co_movement_pattern_passes(self):
        """When co-movement is NOT ai_adoption_expected, CQ degradation is fine."""
        understand = {
            "co_movement_pattern": {
                "pattern_name": "ranking_regression",
                "match_score": 0.85,
            }
        }
        result = {
            "hypotheses": [
                {
                    "hypothesis_id": "h1",
                    "archetype": "click_quality_degradation",
                    "is_contrarian": False,
                },
            ]
        }
        assert rule_hypotheses_consistent_with_co_movement(
            result, understand_result=understand
        ) is None

    def test_no_understand_result_passes(self):
        """When no understand_result is provided, rule should pass (no data to check)."""
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "click_quality_degradation", "is_contrarian": False},
            ]
        }
        assert rule_hypotheses_consistent_with_co_movement(result) is None

    def test_no_co_movement_pattern_passes(self):
        """When understand_result has no co_movement_pattern, rule should pass."""
        understand = {"co_movement_pattern": {}}
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "click_quality_degradation", "is_contrarian": False},
            ]
        }
        assert rule_hypotheses_consistent_with_co_movement(
            result, understand_result=understand
        ) is None

    # -- rule_mix_shift_considered_when_detected -------------------------------

    def test_mix_shift_detected_no_hypothesis_fails(self):
        """When mix-shift explains >25% of movement but no mix-shift hypothesis, fail.

        Mix-shift causes 30-40% of Enterprise metric movements — ignoring it
        means missing the root cause in a huge fraction of investigations.
        """
        understand = {
            "mix_shift_result": {
                "detected": True,
                "contribution_pct": 0.35,
            }
        }
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "ranking_regression"},
                {"hypothesis_id": "h2", "archetype": "connector_degradation"},
            ]
        }
        msg = rule_mix_shift_considered_when_detected(result, understand_result=understand)
        assert msg is not None
        assert "mix-shift" in msg.lower() or "Mix-shift" in msg

    def test_mix_shift_detected_with_mix_shift_hypothesis_passes(self):
        """When mix-shift detected AND a mix-shift hypothesis exists, it should pass."""
        understand = {
            "mix_shift_result": {
                "detected": True,
                "contribution_pct": 0.40,
            }
        }
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "ranking_regression"},
                {"hypothesis_id": "h2", "archetype": "mix_shift"},
            ]
        }
        assert rule_mix_shift_considered_when_detected(
            result, understand_result=understand
        ) is None

    def test_mix_shift_detected_with_segment_mix_shift_hypothesis_passes(self):
        """archetype='segment_mix_shift' should also count as a mix-shift hypothesis."""
        understand = {
            "mix_shift_result": {
                "detected": True,
                "contribution_pct": 0.30,
            }
        }
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "segment_mix_shift"},
            ]
        }
        assert rule_mix_shift_considered_when_detected(
            result, understand_result=understand
        ) is None

    def test_mix_shift_not_detected_passes(self):
        """When mix-shift was not detected, the rule should pass regardless."""
        understand = {
            "mix_shift_result": {
                "detected": False,
                "contribution_pct": 0.10,
            }
        }
        result = {"hypotheses": [{"archetype": "ranking_regression"}]}
        assert rule_mix_shift_considered_when_detected(
            result, understand_result=understand
        ) is None

    def test_mix_shift_below_threshold_passes(self):
        """When mix-shift contribution is <= 25%, rule should pass even if detected."""
        understand = {
            "mix_shift_result": {
                "detected": True,
                "contribution_pct": 0.20,  # Below 0.25 threshold
            }
        }
        result = {"hypotheses": [{"archetype": "ranking_regression"}]}
        assert rule_mix_shift_considered_when_detected(
            result, understand_result=understand
        ) is None

    def test_mix_shift_no_understand_result_passes(self):
        """When no understand_result is provided, rule should pass."""
        result = {"hypotheses": [{"archetype": "ranking_regression"}]}
        assert rule_mix_shift_considered_when_detected(result) is None

    def test_mix_shift_empty_mix_shift_result_passes(self):
        """When mix_shift_result is empty dict, rule should pass."""
        understand = {"mix_shift_result": {}}
        result = {"hypotheses": [{"archetype": "ranking_regression"}]}
        assert rule_mix_shift_considered_when_detected(
            result, understand_result=understand
        ) is None


# =============================================================================
# TestDispatchRules
# =============================================================================

class TestDispatchRules:
    """Tests for DISPATCH stage business rules."""

    # -- rule_each_finding_has_evidence ---------------------------------------

    def test_finding_with_no_evidence_fails(self):
        """A finding without evidence is an opinion, not a diagnosis."""
        msg = rule_each_finding_has_evidence({
            "findings": [
                {
                    "agent_name": "test_agent",
                    "hypothesis_id": "h1",
                    "evidence": [],
                    "narrative": "I think the ranking is broken",
                },
            ]
        })
        assert msg is not None
        assert "evidence" in msg.lower()

    def test_finding_with_missing_evidence_key_fails(self):
        """Finding without 'evidence' key should fail."""
        msg = rule_each_finding_has_evidence({
            "findings": [{"agent_name": "test", "hypothesis_id": "h1"}]
        })
        assert msg is not None

    def test_finding_with_evidence_passes(self):
        """Finding with non-empty evidence should pass."""
        assert rule_each_finding_has_evidence({
            "findings": [
                {
                    "agent_name": "test",
                    "hypothesis_id": "h1",
                    "evidence": [{"metric": "ndcg", "direction": "down"}],
                },
            ]
        }) is None

    def test_multiple_findings_one_without_evidence_fails(self):
        """If any finding lacks evidence, the whole check fails."""
        msg = rule_each_finding_has_evidence({
            "findings": [
                {"agent_name": "a", "hypothesis_id": "h1", "evidence": [{"data": True}]},
                {"agent_name": "b", "hypothesis_id": "h2", "evidence": []},
            ]
        })
        assert msg is not None
        assert "h2" in msg

    def test_no_findings_passes(self):
        """Empty findings list should pass (no findings to check)."""
        assert rule_each_finding_has_evidence({"findings": []}) is None

    # -- rule_narrative_data_coherence ----------------------------------------

    def test_evidence_up_narrative_declined_fails(self):
        """Evidence says UP but narrative says 'dropped' — narrative drift detected."""
        msg = rule_narrative_data_coherence({
            "findings": [
                {
                    "hypothesis_id": "h1",
                    "narrative": "The metric dropped significantly after the change",
                    "evidence": [{"direction": "up"}],
                },
            ]
        })
        assert msg is not None
        assert "mismatch" in msg.lower() or "drift" in msg.lower()

    def test_evidence_down_narrative_increased_fails(self):
        """Evidence says DOWN but narrative says 'increased' — narrative drift."""
        msg = rule_narrative_data_coherence({
            "findings": [
                {
                    "hypothesis_id": "h1",
                    "narrative": "The metric increased after the deployment",
                    "evidence": [{"direction": "down"}],
                },
            ]
        })
        assert msg is not None

    def test_consistent_up_narrative_passes(self):
        """Evidence UP + narrative uses increase language should pass."""
        assert rule_narrative_data_coherence({
            "findings": [
                {
                    "hypothesis_id": "h1",
                    "narrative": "The metric rose 4% after the change",
                    "evidence": [{"direction": "up"}],
                },
            ]
        }) is None

    def test_consistent_down_narrative_passes(self):
        """Evidence DOWN + narrative uses decline language should pass."""
        assert rule_narrative_data_coherence({
            "findings": [
                {
                    "hypothesis_id": "h1",
                    "narrative": "NDCG dropped after the model update",
                    "evidence": [{"direction": "down"}],
                },
            ]
        }) is None

    def test_no_direction_in_evidence_passes(self):
        """Evidence without a direction field should not trigger a coherence check."""
        assert rule_narrative_data_coherence({
            "findings": [
                {
                    "hypothesis_id": "h1",
                    "narrative": "The metric dropped significantly",
                    "evidence": [{"metric": "ndcg", "value": 0.5}],
                },
            ]
        }) is None

    def test_narrative_with_both_directions_passes_when_evidence_up(self):
        """Narrative mentioning both increase and decrease words should pass for UP evidence.

        The rule checks that decline words are present WITHOUT increase words.
        If both are present, it's ambiguous but not flagged.
        """
        assert rule_narrative_data_coherence({
            "findings": [
                {
                    "hypothesis_id": "h1",
                    "narrative": "The metric dropped initially but then rose to a new high",
                    "evidence": [{"direction": "up"}],
                },
            ]
        }) is None


# =============================================================================
# TestSynthesizeRules
# =============================================================================

class TestSynthesizeRules:
    """Tests for SYNTHESIZE stage business rules."""

    # -- rule_all_mandatory_sections_present -----------------------------------

    def test_missing_single_section_fails(self):
        """Missing even one of the 7 mandatory sections should fail."""
        # Has 6 of 7 — missing 'validation_summary'
        result = {
            "tldr": "Summary",
            "confidence_grade": "High",
            "severity": "P1",
            "root_cause": "Ranking regression",
            "dimensional_breakdown": "Standard tier",
            "hypothesis_and_evidence": "Confirmed",
            # validation_summary is missing
        }
        msg = rule_all_mandatory_sections_present(result)
        assert msg is not None
        assert "validation_summary" in msg

    def test_empty_section_fails(self):
        """A section that exists but is empty string should fail."""
        result = {
            "tldr": "",  # Empty
            "confidence_grade": "High",
            "severity": "P1",
            "root_cause": "Ranking regression",
            "dimensional_breakdown": "Standard tier",
            "hypothesis_and_evidence": "Confirmed",
            "validation_summary": "Checked",
        }
        msg = rule_all_mandatory_sections_present(result)
        assert msg is not None
        assert "tldr" in msg

    def test_all_sections_present_passes(self, valid_synthesis_report):
        """All 7 mandatory sections filled should pass."""
        assert rule_all_mandatory_sections_present(valid_synthesis_report) is None

    def test_multiple_missing_sections_listed(self):
        """Multiple missing sections should all appear in the violation message."""
        msg = rule_all_mandatory_sections_present({})
        assert msg is not None
        # All 7 should be listed as missing
        for section in ["tldr", "confidence_grade", "severity", "root_cause",
                        "dimensional_breakdown", "hypothesis_and_evidence", "validation_summary"]:
            assert section in msg

    # -- rule_effect_size_proportionality -------------------------------------

    def test_p0_with_minor_language_fails(self):
        """P0 severity + 'minor' in tldr = minimizing a critical incident."""
        result = {
            "severity": "P0",
            "tldr": "A minor drop in click quality was observed.",
            "root_cause": "Ranking regression caused significant impact.",
        }
        msg = rule_effect_size_proportionality(result)
        assert msg is not None
        assert "minor" in msg
        assert "P0" in msg

    def test_p0_with_slight_in_root_cause_fails(self):
        """P0 severity + 'slight' in root_cause should fail."""
        result = {
            "severity": "P0",
            "tldr": "Critical ranking failure detected.",
            "root_cause": "A slight change in the model caused this.",
        }
        msg = rule_effect_size_proportionality(result)
        assert msg is not None
        assert "slight" in msg

    def test_p0_without_minimizing_language_passes(self):
        """P0 severity with strong language should pass."""
        result = {
            "severity": "P0",
            "tldr": "Critical ranking failure impacting all tenants.",
            "root_cause": "Complete model regression in ranking pipeline.",
        }
        assert rule_effect_size_proportionality(result) is None

    def test_p1_with_minor_language_passes(self):
        """Non-P0 severity should not trigger the proportionality check."""
        result = {
            "severity": "P1",
            "tldr": "A minor drop in click quality was observed.",
            "root_cause": "Slight change in ranking.",
        }
        assert rule_effect_size_proportionality(result) is None

    def test_p0_checks_all_minimizing_words(self):
        """All minimizing words should be caught for P0."""
        minimizing_words = ["minor", "slight", "small", "marginal", "negligible", "trivial"]
        for word in minimizing_words:
            result = {
                "severity": "P0",
                "tldr": f"This was a {word} incident.",
                "root_cause": "Big problem.",
            }
            msg = rule_effect_size_proportionality(result)
            assert msg is not None, f"'{word}' should be caught as minimizing language"

    # -- rule_upgrade_condition_stated -----------------------------------------

    def test_missing_upgrade_condition_fails(self):
        """Missing upgrade_condition means the DS has no next step."""
        msg = rule_upgrade_condition_stated({})
        assert msg is not None
        assert "upgrade_condition" in msg

    def test_empty_upgrade_condition_fails(self):
        """Empty string upgrade_condition should fail."""
        msg = rule_upgrade_condition_stated({"upgrade_condition": ""})
        assert msg is not None

    def test_present_upgrade_condition_passes(self):
        """Non-empty upgrade_condition should pass."""
        assert rule_upgrade_condition_stated({
            "upgrade_condition": "Would upgrade to High if rollback confirms recovery"
        }) is None


# =============================================================================
# TestCLI — python -m contracts.seam_validator
# =============================================================================

class TestCLI:
    """Tests for the CLI interface of seam_validator."""

    def _run_cli(self, stage: str, data: dict, understand_data: dict = None) -> subprocess.CompletedProcess:
        """Helper to run the CLI and return the result."""
        # Write input data to a temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            input_path = f.name

        cmd = [
            sys.executable, "-m", "contracts.seam_validator",
            "--stage", stage,
            "--input", input_path,
        ]

        understand_path = None
        if understand_data:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                json.dump(understand_data, f)
                understand_path = f.name
            cmd.extend(["--understand-input", understand_path])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
                timeout=30,
            )
            return result
        finally:
            os.unlink(input_path)
            if understand_path:
                os.unlink(understand_path)

    def test_cli_understand_pass(self, valid_understand_result):
        """CLI should exit 0 and output JSON with passed=true for valid UNDERSTAND."""
        result = self._run_cli("understand", valid_understand_result)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["passed"] is True
        assert output["stage"] == "UNDERSTAND"

    def test_cli_understand_fail(self):
        """CLI should exit 1 and output JSON with remediation for failed UNDERSTAND."""
        result = self._run_cli("understand", {
            "data_quality_status": "fail",
            "metric_direction": "down",
        })
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["passed"] is False
        assert "remediation" in output

    def test_cli_hypothesize_pass(self, valid_hypothesis_set, valid_understand_result):
        """CLI should handle HYPOTHESIZE stage with understand-input."""
        result = self._run_cli(
            "hypothesize",
            valid_hypothesis_set,
            understand_data=valid_understand_result,
        )
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["passed"] is True

    def test_cli_hypothesize_fail(self):
        """CLI should exit 1 for HYPOTHESIZE with too few hypotheses (soft gate)."""
        result = self._run_cli("hypothesize", {"hypotheses": []})
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["passed"] is False
        assert output["tier"] == "soft"

    def test_cli_synthesize_fail(self):
        """CLI should exit 1 for SYNTHESIZE with missing sections (retry gate)."""
        result = self._run_cli("synthesize", {"severity": "P1"})
        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert output["passed"] is False
        assert "remediation" in output

    def test_cli_output_is_valid_json(self, valid_understand_result):
        """CLI output should always be valid JSON regardless of pass/fail."""
        # Pass case
        result = self._run_cli("understand", valid_understand_result)
        json.loads(result.stdout)  # Should not raise

        # Fail case
        result = self._run_cli("understand", {
            "data_quality_status": "fail",
            "metric_direction": "down",
        })
        json.loads(result.stdout)  # Should not raise


# =============================================================================
# TestGateTierConfig
# =============================================================================

class TestGateTierConfig:
    """Tests that gate tier configuration matches the design spec."""

    def test_understand_is_hard(self):
        """UNDERSTAND must be hard — garbage in = stop."""
        assert GATE_TIERS["UNDERSTAND"] == "hard"

    def test_hypothesize_is_soft(self):
        """HYPOTHESIZE must be soft — something is better than nothing."""
        assert GATE_TIERS["HYPOTHESIZE"] == "soft"

    def test_dispatch_is_soft(self):
        """DISPATCH must be soft — one bad finding shouldn't kill everything."""
        assert GATE_TIERS["DISPATCH"] == "soft"

    def test_synthesize_is_retry(self):
        """SYNTHESIZE must be retry — missing section is usually fixable."""
        assert GATE_TIERS["SYNTHESIZE"] == "retry"
