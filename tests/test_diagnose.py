"""Tests for validation checks and confidence scoring."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from tools.diagnose import (
    check_logging_artifact,
    check_decomposition_completeness,
    check_temporal_consistency,
    check_mix_shift_threshold,
    compute_confidence,
    run_diagnosis,
    verify_diagnosis,
    _extract_explained_pct,
    _extract_mix_shift_pct,
    _build_primary_hypothesis,
    _build_action_items,
    _get_top_segment_contribution,
)


class TestLoggingArtifact:
    """Validation Check #1: Overnight step-change detection."""

    def test_flags_overnight_step_change(self):
        step_change_result = {"detected": True, "change_day_index": 4, "magnitude_pct": 3.5}
        result = check_logging_artifact(step_change_result)
        assert result["status"] == "HALT"
        assert result["check"] == "logging_artifact"

    def test_passes_no_step_change(self):
        step_change_result = {"detected": False}
        result = check_logging_artifact(step_change_result)
        assert result["status"] == "PASS"


class TestDecompositionCompleteness:
    """Validation Check #2: Segments must explain >=90% of total drop."""

    def test_passes_when_complete(self):
        result = check_decomposition_completeness(explained_pct=94.0)
        assert result["status"] == "PASS"

    def test_warns_when_incomplete(self):
        result = check_decomposition_completeness(explained_pct=85.0)
        assert result["status"] == "WARN"

    def test_halts_when_very_incomplete(self):
        result = check_decomposition_completeness(explained_pct=65.0)
        assert result["status"] == "HALT"


class TestTemporalConsistency:
    """Validation Check #3: Metric must change AFTER proposed cause."""

    def test_passes_when_consistent(self):
        result = check_temporal_consistency(
            cause_date_index=3, metric_change_date_index=4
        )
        assert result["status"] == "PASS"

    def test_halts_when_metric_before_cause(self):
        result = check_temporal_consistency(
            cause_date_index=5, metric_change_date_index=2
        )
        assert result["status"] == "HALT"


class TestMixShiftThreshold:
    """Validation Check #4: Flag when mix-shift >= 30%."""

    def test_flags_high_mix_shift(self):
        result = check_mix_shift_threshold(mix_shift_pct=45.0)
        assert result["status"] == "INVESTIGATE"

    def test_passes_low_mix_shift(self):
        result = check_mix_shift_threshold(mix_shift_pct=12.0)
        assert result["status"] == "PASS"


class TestConfidence:
    """Test confidence level assignment."""

    def test_high_confidence(self):
        checks = [
            {"status": "PASS"}, {"status": "PASS"},
            {"status": "PASS"}, {"status": "PASS"},
        ]
        result = compute_confidence(
            checks=checks, explained_pct=94.0,
            evidence_lines=3, has_historical_precedent=True,
        )
        assert result["level"] == "High"

    def test_medium_confidence(self):
        checks = [
            {"status": "PASS"}, {"status": "WARN"},
            {"status": "PASS"}, {"status": "PASS"},
        ]
        result = compute_confidence(
            checks=checks, explained_pct=87.0,
            evidence_lines=2, has_historical_precedent=False,
        )
        assert result["level"] == "Medium"

    def test_low_confidence(self):
        checks = [
            {"status": "PASS"}, {"status": "PASS"},
            {"status": "PASS"}, {"status": "INVESTIGATE"},
        ]
        result = compute_confidence(
            checks=checks, explained_pct=75.0,
            evidence_lines=1, has_historical_precedent=False,
        )
        assert result["level"] == "Low"

    def test_includes_upgrade_condition(self):
        result = compute_confidence(
            checks=[{"status": "PASS"}] * 4,
            explained_pct=87.0,
            evidence_lines=2,
            has_historical_precedent=False,
        )
        assert "would_upgrade_if" in result
        assert result["would_upgrade_if"] is not None


class TestRunDiagnosis:
    """Test the full diagnosis pipeline."""

    def test_runs_on_decomposition_output(self, sample_metric_rows):
        from tools.decompose import run_decomposition
        decomp = run_decomposition(sample_metric_rows, "click_quality_value",
                                   dimensions=["tenant_tier"])
        result = run_diagnosis(decomposition=decomp)
        assert "confidence" in result
        assert "validation_checks" in result
        assert result["confidence"]["level"] in ["High", "Medium", "Low"]

    def test_includes_all_4_checks(self, sample_metric_rows):
        from tools.decompose import run_decomposition
        decomp = run_decomposition(sample_metric_rows, "click_quality_value",
                                   dimensions=["tenant_tier"])
        result = run_diagnosis(decomposition=decomp)
        check_names = [c["check"] for c in result["validation_checks"]]
        assert "logging_artifact" in check_names
        assert "decomposition_completeness" in check_names
        assert "temporal_consistency" in check_names
        assert "mix_shift" in check_names


# ======================================================================
# Edge-case tests: Validation check combinations
# ======================================================================


class TestCheckCombinations:
    """Test combinations of check statuses (all HALT, all INVESTIGATE, mixed)."""

    def test_all_checks_halt_gives_low_confidence(self):
        """When every check returns HALT, confidence must be Low.

        All 4 checks halting means we have a logging artifact, incomplete
        decomposition, broken temporal ordering, AND significant mix-shift.
        The diagnosis is untrustworthy.
        """
        # Build checks: all 4 are HALT (worst case)
        checks = [
            {"check": "logging_artifact", "status": "HALT"},
            {"check": "decomposition_completeness", "status": "HALT"},
            {"check": "temporal_consistency", "status": "HALT"},
            {"check": "mix_shift", "status": "HALT"},
        ]
        result = compute_confidence(
            checks=checks,
            explained_pct=50.0,       # Low explained pct too
            evidence_lines=1,          # Minimal evidence
            has_historical_precedent=False,
        )
        # 4 non-PASS checks (>=2) triggers Low, plus low explained_pct (<80%)
        assert result["level"] == "Low"
        # Should suggest resolving failing checks in upgrade advice
        assert result["would_upgrade_if"] is not None
        assert "resolve" in result["would_upgrade_if"]

    def test_all_checks_investigate_gives_low_confidence(self):
        """When every check returns INVESTIGATE, confidence must be Low.

        INVESTIGATE is a non-PASS status. 4 non-PASS checks >= 2 threshold,
        so this triggers the Low confidence path.
        """
        checks = [
            {"check": "logging_artifact", "status": "INVESTIGATE"},
            {"check": "decomposition_completeness", "status": "INVESTIGATE"},
            {"check": "temporal_consistency", "status": "INVESTIGATE"},
            {"check": "mix_shift", "status": "INVESTIGATE"},
        ]
        result = compute_confidence(
            checks=checks,
            explained_pct=85.0,        # Decent explained pct
            evidence_lines=3,          # Plenty of evidence
            has_historical_precedent=True,
        )
        # 4 non-PASS checks (>=2) triggers the "multiple_non_pass" Low path
        assert result["level"] == "Low"

    def test_mixed_halt_and_pass_with_good_metrics_gives_medium(self):
        """One HALT + three PASS with good metrics should yield Medium.

        One non-PASS check is not enough to trigger the multiple_non_pass
        Low path. With good explained_pct and evidence, this lands in Medium.
        """
        checks = [
            {"check": "logging_artifact", "status": "HALT"},
            {"check": "decomposition_completeness", "status": "PASS"},
            {"check": "temporal_consistency", "status": "PASS"},
            {"check": "mix_shift", "status": "PASS"},
        ]
        result = compute_confidence(
            checks=checks,
            explained_pct=92.0,        # Good
            evidence_lines=3,
            has_historical_precedent=True,
        )
        # One non-PASS prevents High, but not enough for Low
        assert result["level"] == "Medium"
        # Should mention resolving the HALT check to upgrade
        assert "logging_artifact" in result["would_upgrade_if"]

    def test_two_non_pass_checks_triggers_low(self):
        """Exactly 2 non-PASS checks hits the >=2 threshold for Low.

        This is the boundary: 1 non-PASS = Medium, 2 non-PASS = Low.
        """
        checks = [
            {"check": "logging_artifact", "status": "HALT"},
            {"check": "decomposition_completeness", "status": "WARN"},
            {"check": "temporal_consistency", "status": "PASS"},
            {"check": "mix_shift", "status": "PASS"},
        ]
        result = compute_confidence(
            checks=checks,
            explained_pct=92.0,
            evidence_lines=3,
            has_historical_precedent=True,
        )
        # 2 non-PASS checks (>=2) triggers Low
        assert result["level"] == "Low"

    def test_warn_and_investigate_mixed(self):
        """WARN + INVESTIGATE are both non-PASS. 2 of them triggers Low."""
        checks = [
            {"check": "logging_artifact", "status": "PASS"},
            {"check": "decomposition_completeness", "status": "WARN"},
            {"check": "temporal_consistency", "status": "PASS"},
            {"check": "mix_shift", "status": "INVESTIGATE"},
        ]
        result = compute_confidence(
            checks=checks,
            explained_pct=92.0,
            evidence_lines=3,
            has_historical_precedent=True,
        )
        # 2 non-PASS checks triggers Low
        assert result["level"] == "Low"


# ======================================================================
# Edge-case tests: Boundary values for explained_pct
# ======================================================================


class TestDecompositionCompletenessBoundary:
    """Boundary value testing at exactly 90%, 80%, 70% thresholds."""

    def test_exactly_90_percent_is_pass(self):
        """90.0% is >= 90% threshold, so it should PASS (not WARN).

        The code uses >= comparison, so the boundary value goes to PASS.
        """
        result = check_decomposition_completeness(explained_pct=90.0)
        assert result["status"] == "PASS"

    def test_just_below_90_percent_is_warn(self):
        """89.9% is < 90% threshold, so it should WARN."""
        result = check_decomposition_completeness(explained_pct=89.9)
        assert result["status"] == "WARN"

    def test_exactly_70_percent_is_warn(self):
        """70.0% is >= 70% threshold, so it should WARN (not HALT).

        The code uses >= comparison for the WARN threshold too.
        """
        result = check_decomposition_completeness(explained_pct=70.0)
        assert result["status"] == "WARN"

    def test_just_below_70_percent_is_halt(self):
        """69.9% is < 70% threshold, so it should HALT."""
        result = check_decomposition_completeness(explained_pct=69.9)
        assert result["status"] == "HALT"

    def test_zero_percent_is_halt(self):
        """0% explained means decomposition found nothing useful."""
        result = check_decomposition_completeness(explained_pct=0.0)
        assert result["status"] == "HALT"

    def test_100_percent_is_pass(self):
        """100% explained is the ideal case -- full coverage."""
        result = check_decomposition_completeness(explained_pct=100.0)
        assert result["status"] == "PASS"


class TestConfidenceBoundaryValues:
    """Boundary testing for the explained_pct thresholds in confidence scoring.

    High confidence requires >=90%, Medium requires >=80%.
    """

    def test_exactly_90_pct_with_all_conditions_gives_high(self):
        """90.0% explained (boundary) + all other High conditions met = High."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=90.0,        # Exactly at High threshold
            evidence_lines=3,
            has_historical_precedent=True,
        )
        assert result["level"] == "High"

    def test_just_below_90_pct_gives_medium(self):
        """89.9% explained (just below High threshold) = Medium even if
        all other conditions met."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=89.9,
            evidence_lines=3,
            has_historical_precedent=True,
        )
        # Misses High because explained_pct < 90
        # But doesn't hit Low because explained_pct >= 80
        assert result["level"] == "Medium"

    def test_exactly_80_pct_gives_medium(self):
        """80.0% explained (boundary for Medium) with enough evidence = Medium."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=80.0,        # Exactly at Medium threshold
            evidence_lines=2,
            has_historical_precedent=False,
        )
        # Misses High (below 90%, no precedent)
        # Not Low (explained >= 80%, evidence >= 2, only 0 non-PASS)
        assert result["level"] == "Medium"

    def test_just_below_80_pct_gives_low(self):
        """79.9% explained (below Medium threshold) = Low."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=79.9,
            evidence_lines=2,
            has_historical_precedent=False,
        )
        # Low because explained_pct < 80%
        assert result["level"] == "Low"


# ======================================================================
# Edge-case tests: Confidence with extreme evidence counts
# ======================================================================


class TestConfidenceEvidenceEdgeCases:
    """Edge cases for evidence_lines and HALT check interactions."""

    def test_zero_evidence_lines_gives_low(self):
        """0 evidence lines is below the minimum (2), so confidence is Low.

        Even with perfect checks and explained_pct, having zero evidence
        means we have no corroboration for the diagnosis.
        """
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=95.0,        # Great coverage
            evidence_lines=0,          # No evidence at all
            has_historical_precedent=True,
        )
        assert result["level"] == "Low"
        # Upgrade advice should mention increasing evidence lines
        assert "evidence lines" in result["would_upgrade_if"]

    def test_one_evidence_line_gives_low(self):
        """1 evidence line is below minimum (2), so still Low."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=95.0,
            evidence_lines=1,
            has_historical_precedent=True,
        )
        assert result["level"] == "Low"

    def test_exactly_two_evidence_lines_escapes_low(self):
        """2 evidence lines is >= minimum (2), so not Low from evidence alone."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=95.0,
            evidence_lines=2,
            has_historical_precedent=True,
        )
        # Not Low (evidence >= 2, explained >= 80, 0 non-PASS)
        # Not High (evidence < 3 for High)
        assert result["level"] == "Medium"

    def test_exactly_three_evidence_lines_with_all_conditions_gives_high(self):
        """3 evidence lines is the minimum for High confidence."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=95.0,
            evidence_lines=3,          # Minimum for High
            has_historical_precedent=True,
        )
        assert result["level"] == "High"

    def test_halt_check_with_high_evidence_still_not_high(self):
        """A single HALT check prevents High confidence even with great metrics.

        This tests the interaction between a HALT check and evidence count.
        The HALT makes all_checks_pass = False, blocking High.
        """
        checks = [
            {"check": "logging_artifact", "status": "HALT"},
            {"check": "decomposition_completeness", "status": "PASS"},
            {"check": "temporal_consistency", "status": "PASS"},
            {"check": "mix_shift", "status": "PASS"},
        ]
        result = compute_confidence(
            checks=checks,
            explained_pct=99.0,        # Nearly perfect
            evidence_lines=5,          # Lots of evidence
            has_historical_precedent=True,
        )
        # One non-PASS blocks High, but only 1 so not Low from multiple_non_pass
        assert result["level"] == "Medium"

    def test_no_historical_precedent_blocks_high(self):
        """Missing historical precedent alone prevents High confidence.

        Everything else is perfect, but without precedent, we land in Medium.
        """
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=99.0,
            evidence_lines=5,
            has_historical_precedent=False,  # Missing
        )
        assert result["level"] == "Medium"
        assert "historical precedent" in result["would_upgrade_if"]


# ======================================================================
# Edge-case tests: Confidence downgrade conditions
# ======================================================================


class TestConfidenceDowngradeConditions:
    """Test the would_downgrade_if field across confidence levels."""

    def test_high_confidence_downgrade_conditions(self):
        """High confidence with exactly 3 evidence lines should warn about
        losing one evidence line."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=91.0,        # < 95 so explained_pct downgrade applies
            evidence_lines=3,          # Exactly at minimum
            has_historical_precedent=True,
        )
        assert result["level"] == "High"
        # Should mention both downgrade risks
        assert result["would_downgrade_if"] is not None
        assert "losing one evidence line" in result["would_downgrade_if"]
        assert "explained_pct drops below 90%" in result["would_downgrade_if"]

    def test_high_confidence_no_downgrade_when_well_above_thresholds(self):
        """High confidence well above all thresholds has no downgrade warning
        only if explained_pct >= 95 AND evidence_lines > 3."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=98.0,        # >= 95, no explained_pct downgrade
            evidence_lines=5,          # > 3, no evidence downgrade
            has_historical_precedent=True,
        )
        assert result["level"] == "High"
        assert result["would_downgrade_if"] is None

    def test_low_confidence_downgrade_is_none(self):
        """Low confidence is the floor -- no further downgrade possible."""
        checks = [
            {"check": "a", "status": "HALT"},
            {"check": "b", "status": "HALT"},
            {"check": "c", "status": "HALT"},
            {"check": "d", "status": "HALT"},
        ]
        result = compute_confidence(
            checks=checks,
            explained_pct=30.0,
            evidence_lines=0,
            has_historical_precedent=False,
        )
        assert result["level"] == "Low"
        assert result["would_downgrade_if"] is None

    def test_medium_confidence_has_downgrade_conditions(self):
        """Medium confidence with borderline metrics should report downgrade risk."""
        checks = [{"status": "PASS"}] * 4
        result = compute_confidence(
            checks=checks,
            explained_pct=82.0,        # < 85, triggers downgrade warning
            evidence_lines=2,          # Exactly at minimum for Medium
            has_historical_precedent=False,
        )
        assert result["level"] == "Medium"
        assert result["would_downgrade_if"] is not None
        # Should warn about losing evidence and explained_pct dropping
        assert "losing one evidence line" in result["would_downgrade_if"]


# ======================================================================
# Edge-case tests: run_diagnosis with empty/missing data
# ======================================================================


class TestRunDiagnosisEdgeCases:
    """Edge cases for the full diagnosis pipeline."""

    def test_empty_decomposition(self):
        """An empty decomposition dict should not crash.

        This simulates the case where the decomposition tool returned
        nothing useful -- maybe the input data was empty or malformed.
        With no co-movement input, the false alarm detection may trigger
        (empty decomposition looks like no movement), giving High confidence.
        """
        result = run_diagnosis(decomposition={})
        # May be High (false alarm override) or Low depending on detection path
        assert result["confidence"]["level"] in ["High", "Low"]
        # Should still produce all structural keys
        assert "validation_checks" in result
        assert "primary_hypothesis" in result
        assert "action_items" in result
        assert len(result["validation_checks"]) == 4

    def test_decomposition_with_empty_dimensional_breakdown(self):
        """Decomposition with dimensional_breakdown={} should handle gracefully.

        The explained_pct extractor should return 0.0 when there are
        no dimensions, triggering HALT on completeness check.
        """
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "direction": "down",
                "severity": "P1",
            },
            "dimensional_breakdown": {},
            "mix_shift": {},
            "dominant_dimension": None,
            "drill_down_recommended": False,
        }
        result = run_diagnosis(decomposition=decomposition)
        # 0% explained -> completeness HALT -> at least 1 non-PASS
        completeness_check = next(
            c for c in result["validation_checks"]
            if c["check"] == "decomposition_completeness"
        )
        assert completeness_check["status"] == "HALT"

    def test_decomposition_with_missing_aggregate(self):
        """Missing 'aggregate' key should not crash.

        The pipeline accesses aggregate.get("severity") for evidence counting.
        With no aggregate, this should gracefully return None/missing.
        """
        decomposition = {
            "dimensional_breakdown": {},
            "mix_shift": {},
        }
        result = run_diagnosis(decomposition=decomposition)
        # Should not crash. Aggregate may get severity override from false alarm
        # detection (empty decomposition looks like no movement = false alarm).
        assert "severity" in result["aggregate"] or result["aggregate"] == {}
        assert result["confidence"]["level"] in ["High", "Medium", "Low"]

    def test_decomposition_with_missing_mix_shift(self):
        """Missing 'mix_shift' key should default to 0% mix-shift."""
        decomposition = {
            "aggregate": {},
            "dimensional_breakdown": {},
        }
        result = run_diagnosis(decomposition=decomposition)
        mix_check = next(
            c for c in result["validation_checks"]
            if c["check"] == "mix_shift"
        )
        # 0% mix-shift -> PASS
        assert mix_check["status"] == "PASS"

    def test_step_change_result_defaults_to_no_detection(self):
        """When step_change_result is None, it should default to no detection."""
        decomposition = {"aggregate": {}, "dimensional_breakdown": {}, "mix_shift": {}}
        result = run_diagnosis(decomposition=decomposition, step_change_result=None)
        logging_check = next(
            c for c in result["validation_checks"]
            if c["check"] == "logging_artifact"
        )
        assert logging_check["status"] == "PASS"

    def test_temporal_indices_default_to_zero(self):
        """When cause/metric date indices are None, both default to 0.

        0 <= 0, so temporal consistency should PASS (cause == metric change).
        """
        decomposition = {"aggregate": {}, "dimensional_breakdown": {}, "mix_shift": {}}
        result = run_diagnosis(
            decomposition=decomposition,
            cause_date_index=None,
            metric_change_date_index=None,
        )
        temporal_check = next(
            c for c in result["validation_checks"]
            if c["check"] == "temporal_consistency"
        )
        assert temporal_check["status"] == "PASS"

    def test_step_change_with_halt_overrides_defaults(self):
        """Providing a step-change result with detected=True should produce HALT."""
        decomposition = {"aggregate": {}, "dimensional_breakdown": {}, "mix_shift": {}}
        step_change = {
            "detected": True,
            "change_day_index": 3,
            "magnitude_pct": 5.0,
        }
        result = run_diagnosis(
            decomposition=decomposition,
            step_change_result=step_change,
        )
        logging_check = next(
            c for c in result["validation_checks"]
            if c["check"] == "logging_artifact"
        )
        assert logging_check["status"] == "HALT"


# ======================================================================
# Edge-case tests: Helper functions
# ======================================================================


class TestExtractExplainedPct:
    """Test the _extract_explained_pct helper for edge cases."""

    def test_empty_dimensional_breakdown_returns_zero(self):
        """No dimensions means 0% explained."""
        assert _extract_explained_pct({"dimensional_breakdown": {}}) == 0.0

    def test_missing_key_returns_zero(self):
        """Decomposition dict without dimensional_breakdown returns 0%."""
        assert _extract_explained_pct({}) == 0.0

    def test_dimension_with_no_segments_returns_zero(self):
        """A dimension entry with empty segments list returns 0%."""
        decomp = {
            "dimensional_breakdown": {
                "tenant_tier": {"segments": []}
            }
        }
        assert _extract_explained_pct(decomp) == 0.0

    def test_picks_highest_explained_dimension(self):
        """When multiple dimensions exist, pick the one with highest total."""
        decomp = {
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"contribution_pct": 60.0},
                        {"contribution_pct": 25.0},
                    ]
                },
                "connector_type": {
                    "segments": [
                        {"contribution_pct": 40.0},
                        {"contribution_pct": 30.0},
                    ]
                },
            }
        }
        # tenant_tier: |60| + |25| = 85
        # connector_type: |40| + |30| = 70
        assert _extract_explained_pct(decomp) == 85.0

    def test_handles_negative_contributions(self):
        """Negative contribution_pct values should be handled via abs()."""
        decomp = {
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"contribution_pct": -80.0},
                        {"contribution_pct": 15.0},
                    ]
                }
            }
        }
        # abs(-80) + abs(15) = 95
        assert _extract_explained_pct(decomp) == 95.0


class TestExtractMixShiftPct:
    """Test the _extract_mix_shift_pct helper."""

    def test_missing_mix_shift_key_returns_zero(self):
        assert _extract_mix_shift_pct({}) == 0.0

    def test_empty_mix_shift_dict_returns_zero(self):
        assert _extract_mix_shift_pct({"mix_shift": {}}) == 0.0

    def test_extracts_valid_value(self):
        assert _extract_mix_shift_pct(
            {"mix_shift": {"mix_shift_contribution_pct": 42.5}}
        ) == 42.5


class TestBuildPrimaryHypothesis:
    """Test _build_primary_hypothesis helper edge cases."""

    def test_no_dominant_dimension(self):
        """When dominant_dimension is None, hypothesis should say so."""
        decomp = {
            "dominant_dimension": None,
            "dimensional_breakdown": {},
            "aggregate": {},
        }
        result = _build_primary_hypothesis(decomp)
        assert result["dimension"] is None
        assert result["segment"] is None
        assert "No dominant dimension" in result["description"]

    def test_dominant_dimension_not_in_breakdown(self):
        """If dominant_dimension key is missing from dimensional_breakdown."""
        decomp = {
            "dominant_dimension": "tenant_tier",
            "dimensional_breakdown": {},  # tenant_tier not present
            "aggregate": {},
        }
        result = _build_primary_hypothesis(decomp)
        assert result["dimension"] is None
        assert "No dominant dimension" in result["description"]

    def test_dominant_dimension_with_empty_segments(self):
        """If the dominant dimension exists but has no segments."""
        decomp = {
            "dominant_dimension": "tenant_tier",
            "dimensional_breakdown": {
                "tenant_tier": {"segments": []}
            },
            "aggregate": {},
        }
        # _build_primary_hypothesis now takes optional co_movement_result
        result = _build_primary_hypothesis(decomp)
        # With no segments, the hypothesis won't report dimension/segment info
        # but should still return a valid result without crashing
        assert result["segment"] is None
        assert isinstance(result["description"], str)


class TestBuildActionItems:
    """Test _build_action_items helper edge cases."""

    def test_all_pass_checks_with_high_confidence(self):
        """All PASS checks + High confidence = no remediation actions except drill-down."""
        checks = [
            {"check": "logging_artifact", "status": "PASS"},
            {"check": "decomposition_completeness", "status": "PASS"},
            {"check": "temporal_consistency", "status": "PASS"},
            {"check": "mix_shift", "status": "PASS"},
        ]
        decomp = {"drill_down_recommended": False}
        actions = _build_action_items(checks, "High", decomp)
        # High confidence -> no confidence-level action
        # All PASS -> no remediation actions
        # No drill-down -> no drill-down action
        assert len(actions) == 0

    def test_halt_logging_artifact_generates_priority_action(self):
        """HALT on logging_artifact should produce a PRIORITY action."""
        checks = [
            {"check": "logging_artifact", "status": "HALT"},
            {"check": "decomposition_completeness", "status": "PASS"},
            {"check": "temporal_consistency", "status": "PASS"},
            {"check": "mix_shift", "status": "PASS"},
        ]
        decomp = {"drill_down_recommended": False}
        # _build_action_items now returns list of dicts with "action" and "owner"
        actions = _build_action_items(checks, "Medium", decomp)
        priority_actions = [a for a in actions if "PRIORITY" in a.get("action", "")]
        assert len(priority_actions) >= 1

    def test_halt_temporal_generates_revise_action(self):
        """HALT on temporal_consistency should advise revising the hypothesis."""
        checks = [
            {"check": "logging_artifact", "status": "PASS"},
            {"check": "decomposition_completeness", "status": "PASS"},
            {"check": "temporal_consistency", "status": "HALT"},
            {"check": "mix_shift", "status": "PASS"},
        ]
        decomp = {"drill_down_recommended": False}
        actions = _build_action_items(checks, "Medium", decomp)
        revise_actions = [a for a in actions if "Revise" in a.get("action", "")]
        assert len(revise_actions) >= 1

    def test_investigate_mix_shift_generates_investigation_action(self):
        """INVESTIGATE on mix_shift should advise comparing per-segment metrics."""
        checks = [
            {"check": "logging_artifact", "status": "PASS"},
            {"check": "decomposition_completeness", "status": "PASS"},
            {"check": "temporal_consistency", "status": "PASS"},
            {"check": "mix_shift", "status": "INVESTIGATE"},
        ]
        decomp = {"drill_down_recommended": False}
        actions = _build_action_items(checks, "Medium", decomp)
        # Action items are now dicts with "action" and "owner" keys
        mix_actions = [a for a in actions if "mix-shift" in a.get("action", "").lower()]
        assert len(mix_actions) >= 1

    def test_low_confidence_adds_gather_evidence_action(self):
        """Low confidence should add a 'gather more evidence' action."""
        checks = [{"check": "c", "status": "PASS"}] * 4
        decomp = {"drill_down_recommended": False}
        actions = _build_action_items(checks, "Low", decomp)
        low_actions = [a for a in actions if "Low confidence" in a.get("action", "")]
        assert len(low_actions) >= 1

    def test_drill_down_recommended_adds_action(self):
        """drill_down_recommended=True should add a drill-down action."""
        checks = [{"check": "c", "status": "PASS"}] * 4
        decomp = {
            "drill_down_recommended": True,
            "dominant_dimension": "tenant_tier",
        }
        actions = _build_action_items(checks, "High", decomp)
        drill_actions = [a for a in actions if "Drill down" in a.get("action", "")]
        assert len(drill_actions) >= 1
        assert "tenant_tier" in drill_actions[0]["action"]


# ======================================================================
# Edge-case tests: Logging artifact check details
# ======================================================================


class TestLoggingArtifactEdgeCases:
    """Additional edge cases for check_logging_artifact."""

    def test_empty_dict_passes(self):
        """An empty dict defaults to detected=False, so should PASS."""
        result = check_logging_artifact({})
        assert result["status"] == "PASS"

    def test_detected_false_explicitly(self):
        """Explicitly setting detected=False should PASS."""
        result = check_logging_artifact({"detected": False, "magnitude_pct": 10.0})
        assert result["status"] == "PASS"

    def test_halt_detail_includes_magnitude(self):
        """When halting, the detail message should mention the magnitude."""
        result = check_logging_artifact({
            "detected": True,
            "change_day_index": 7,
            "magnitude_pct": 12.5,
        })
        assert result["status"] == "HALT"
        assert "12.5%" in result["detail"]
        assert "day index 7" in result["detail"]

    def test_missing_fields_defaults(self):
        """detected=True but missing other fields should still HALT gracefully."""
        result = check_logging_artifact({"detected": True})
        assert result["status"] == "HALT"
        assert "unknown" in result["detail"]


# ======================================================================
# Edge-case tests: Temporal consistency
# ======================================================================


class TestTemporalConsistencyEdgeCases:
    """Additional edge cases for check_temporal_consistency."""

    def test_same_day_cause_and_effect_passes(self):
        """Cause and effect on the same day should PASS (coincident)."""
        result = check_temporal_consistency(
            cause_date_index=5, metric_change_date_index=5
        )
        assert result["status"] == "PASS"
        assert "0 day(s)" in result["detail"]

    def test_cause_much_before_effect_passes(self):
        """Cause 10 days before effect should PASS."""
        result = check_temporal_consistency(
            cause_date_index=0, metric_change_date_index=10
        )
        assert result["status"] == "PASS"
        assert "10 day(s)" in result["detail"]

    def test_negative_date_indices(self):
        """Negative date indices should still work (relative dates)."""
        result = check_temporal_consistency(
            cause_date_index=-3, metric_change_date_index=-1
        )
        assert result["status"] == "PASS"

    def test_metric_one_day_before_cause_halts(self):
        """Metric changing 1 day before cause should HALT."""
        result = check_temporal_consistency(
            cause_date_index=5, metric_change_date_index=4
        )
        assert result["status"] == "HALT"
        assert "1 day(s)" in result["detail"]


# ======================================================================
# Edge-case tests: Mix-shift threshold boundary
# ======================================================================


class TestMixShiftBoundary:
    """Boundary testing for the 30% mix-shift threshold."""

    def test_exactly_30_percent_is_investigate(self):
        """30.0% is >= 30% threshold, should trigger INVESTIGATE."""
        result = check_mix_shift_threshold(mix_shift_pct=30.0)
        assert result["status"] == "INVESTIGATE"

    def test_just_below_30_percent_passes(self):
        """29.9% is < 30% threshold, should PASS."""
        result = check_mix_shift_threshold(mix_shift_pct=29.9)
        assert result["status"] == "PASS"

    def test_zero_mix_shift_passes(self):
        """0% mix-shift means purely behavioral change."""
        result = check_mix_shift_threshold(mix_shift_pct=0.0)
        assert result["status"] == "PASS"

    def test_100_percent_mix_shift_investigates(self):
        """100% mix-shift means the entire movement is compositional."""
        result = check_mix_shift_threshold(mix_shift_pct=100.0)
        assert result["status"] == "INVESTIGATE"


# ======================================================================
# Edge-case tests: run_diagnosis action items completeness
# ======================================================================


class TestRunDiagnosisActionItems:
    """Test that run_diagnosis generates correct action items for various scenarios."""

    def test_all_halt_checks_produce_multiple_actions(self):
        """When all checks HALT, each HALT should generate its own action."""
        decomposition = {
            "aggregate": {"severity": "P0", "metric": "click_quality_value", "direction": "down"},
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [{
                        "segment_value": "standard",
                        "contribution_pct": 40.0,
                        "baseline_mean": 0.280,
                        "current_mean": 0.245,
                    }]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 0.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": False,
        }
        # Force all 4 checks to produce non-PASS results:
        # - Step change detected -> HALT on logging_artifact
        # - Low explained_pct -> HALT on decomposition_completeness
        # - Metric before cause -> HALT on temporal_consistency
        # - High mix-shift -> INVESTIGATE on mix_shift
        step_change = {"detected": True, "change_day_index": 1, "magnitude_pct": 5.0}
        result = run_diagnosis(
            decomposition=decomposition,
            step_change_result=step_change,
            cause_date_index=10,             # Cause AFTER effect
            metric_change_date_index=2,
        )
        # Should have action items from:
        # - logging_artifact HALT
        # - temporal_consistency HALT
        # - Low confidence advice
        # Note: decomposition_completeness depends on the explained_pct
        assert len(result["action_items"]) >= 2

    def test_clean_diagnosis_with_drill_down(self):
        """Clean diagnosis with drill_down_recommended should only have drill-down action."""
        decomposition = {
            "aggregate": {"severity": "P1"},
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {
                            "segment_value": "standard",
                            "contribution_pct": 85.0,
                            "baseline_mean": 0.280,
                            "current_mean": 0.245,
                        }
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 5.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        result = run_diagnosis(decomposition=decomposition)
        # Drill-down action should be present. Action items are now dicts.
        drill_actions = [a for a in result["action_items"] if "Drill down" in a.get("action", "")]
        assert len(drill_actions) >= 1


# ======================================================================
# CLI subprocess tests for diagnose.py
# ======================================================================

# Path to the project root, resolved from this test file
PROJECT_ROOT = Path(__file__).parent.parent


class TestDiagnoseCLI:
    """Test the diagnose.py CLI via subprocess.

    These tests verify the CLI interface that Claude Code uses to invoke
    the tool via Bash. They test the complete pipeline from file input
    to JSON output on stdout.
    """

    def test_cli_with_valid_decomposition_json(self, tmp_path):
        """CLI should produce valid JSON output from a decomposition file."""
        # Arrange: create a minimal decomposition JSON
        decomp = {
            "aggregate": {
                "metric": "click_quality_value",
                "direction": "down",
                "severity": "P1",
                "baseline_mean": 0.280,
                "current_mean": 0.262,
                "absolute_delta": -0.018,
                "relative_delta_pct": -6.25,
                "error": None,
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {
                            "segment_value": "standard",
                            "contribution_pct": 85.0,
                            "baseline_mean": 0.280,
                            "current_mean": 0.245,
                            "delta": -0.035,
                        }
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 10.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        input_file = tmp_path / "decomposition.json"
        input_file.write_text(json.dumps(decomp))

        # Act: run the CLI
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "diagnose.py"),
             "--input", str(input_file)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Assert: should succeed and produce valid JSON
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert "confidence" in output
        assert "validation_checks" in output
        assert output["confidence"]["level"] in ["High", "Medium", "Low"]

    def test_cli_missing_input_file_exits_with_error(self, tmp_path):
        """CLI should exit with code 1 and error JSON when file doesn't exist."""
        fake_path = tmp_path / "nonexistent.json"

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "diagnose.py"),
             "--input", str(fake_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert "error" in output

    def test_cli_with_step_change_json(self, tmp_path):
        """CLI should accept --step-change-json flag and use it."""
        decomp = {
            "aggregate": {},
            "dimensional_breakdown": {},
            "mix_shift": {},
        }
        step_change = {
            "detected": True,
            "change_day_index": 3,
            "magnitude_pct": 8.0,
        }
        decomp_file = tmp_path / "decomp.json"
        decomp_file.write_text(json.dumps(decomp))
        step_file = tmp_path / "step_change.json"
        step_file.write_text(json.dumps(step_change))

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "diagnose.py"),
             "--input", str(decomp_file),
             "--step-change-json", str(step_file)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        # The step-change should have triggered a HALT on logging_artifact
        logging_check = next(
            c for c in output["validation_checks"]
            if c["check"] == "logging_artifact"
        )
        assert logging_check["status"] == "HALT"

    def test_cli_with_cause_and_metric_day_flags(self, tmp_path):
        """CLI should accept --cause-day and --metric-change-day flags."""
        decomp = {
            "aggregate": {},
            "dimensional_breakdown": {},
            "mix_shift": {},
        }
        decomp_file = tmp_path / "decomp.json"
        decomp_file.write_text(json.dumps(decomp))

        # Cause after metric change -> temporal HALT
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "diagnose.py"),
             "--input", str(decomp_file),
             "--cause-day", "10",
             "--metric-change-day", "3"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        temporal_check = next(
            c for c in output["validation_checks"]
            if c["check"] == "temporal_consistency"
        )
        assert temporal_check["status"] == "HALT"

    def test_cli_missing_step_change_file_exits_with_error(self, tmp_path):
        """CLI should exit with code 1 when --step-change-json file doesn't exist."""
        decomp = {"aggregate": {}, "dimensional_breakdown": {}, "mix_shift": {}}
        decomp_file = tmp_path / "decomp.json"
        decomp_file.write_text(json.dumps(decomp))
        fake_step = tmp_path / "nonexistent_step.json"

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "diagnose.py"),
             "--input", str(decomp_file),
             "--step-change-json", str(fake_step)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 1
        output = json.loads(result.stdout)
        assert "error" in output

    def test_cli_with_co_movement_and_trust_gate_json(self, tmp_path):
        """CLI should load co-movement and trust-gate JSON inputs."""
        decomp = {
            "aggregate": {"metric": "click_quality_value", "severity": "P0"},
            "dimensional_breakdown": {},
            "mix_shift": {},
        }
        co_movement = {"likely_cause": "ranking_relevance_regression", "is_positive": False}
        trust_gate = {"status": "fail", "reason": "freshness too stale"}
        decomp_file = tmp_path / "decomp.json"
        decomp_file.write_text(json.dumps(decomp))
        co_movement_file = tmp_path / "co_movement.json"
        co_movement_file.write_text(json.dumps(co_movement))
        trust_gate_file = tmp_path / "trust_gate.json"
        trust_gate_file.write_text(json.dumps(trust_gate))

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "tools" / "diagnose.py"),
             "--input", str(decomp_file),
             "--co-movement-json", str(co_movement_file),
             "--trust-gate-json", str(trust_gate_file)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["decision_status"] == "blocked_by_data_quality"


class TestDecisionStatus:
    """Decision status should align with trust gate and overlap rules."""

    def test_trust_gate_fail_blocks_definitive_diagnosis(self):
        decomp = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P1",
                "direction": "down",
                "relative_delta_pct": -3.0,
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 80.0, "delta": -0.03}
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 5.0},
            "dominant_dimension": "tenant_tier",
        }
        result = run_diagnosis(
            decomposition=decomp,
            co_movement_result={"likely_cause": "ranking_relevance_regression", "is_positive": False},
            trust_gate_result={"status": "fail", "reason": "freshness too stale"},
        )
        assert result["decision_status"] == "blocked_by_data_quality"
        assert result["aggregate"]["severity"] == "blocked"
        assert result["aggregate"]["original_severity"] == "P1"
        assert "blocked" in result["primary_hypothesis"]["description"].lower()
        assert result["confidence"]["level"] != "High"

    def test_unresolved_overlap_returns_insufficient_evidence(self):
        decomp = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P0",
                "direction": "down",
                "relative_delta_pct": -10.0,
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 55.0, "delta": -0.05}
                    ]
                },
                "ai_enablement": {
                    "segments": [
                        {"segment_value": "ai_off", "contribution_pct": 51.0, "delta": -0.05}
                    ]
                },
            },
            "mix_shift": {"mix_shift_contribution_pct": 8.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        result = run_diagnosis(
            decomposition=decomp,
            co_movement_result={"likely_cause": "ranking_relevance_regression", "is_positive": False},
            trust_gate_result={"status": "pass", "reason": "ok"},
        )
        assert result["decision_status"] == "insufficient_evidence"
        assert result["confidence"]["level"] in ("Medium", "Low")


# ======================================================================
# v1.2 Group 3: New tests for diagnostic logic fixes
# ======================================================================


class TestFalseAlarmDeltaGuard:
    """Test that false alarm path (b) respects the per-metric noise threshold.

    Path (b) activates when: severity is P2, co-movement is unknown, and no
    segment dominates. The delta guard prevents this from triggering when the
    actual metric movement exceeds the noise threshold for that metric.
    """

    def test_path_b_blocked_by_large_delta(self):
        """P2 + unknown + segment < 50% BUT delta 5% → should NOT be false alarm.

        A 5% relative delta in Click Quality (noise threshold 4%) is a real signal.
        The delta guard should prevent false alarm classification.
        """
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P2",
                "relative_delta_pct": -5.0,  # 5% > 4% noise threshold
                "direction": "down",
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 40.0,
                         "baseline_mean": 0.28, "current_mean": 0.266},
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 5.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        # co-movement unknown, P2 severity, segment < 50% — would be false alarm
        # without the delta guard. But delta 5% > 4% threshold blocks it.
        result = run_diagnosis(
            decomposition=decomposition,
            co_movement_result={"likely_cause": "unknown_pattern", "is_positive": False},
        )
        # Should NOT be classified as false alarm
        assert result["primary_hypothesis"]["archetype"] != "false_alarm"
        assert result["aggregate"].get("severity") != "normal"

    def test_path_b_works_for_small_delta(self):
        """P2 + unknown + segment < 50% AND delta 0.3% → IS false alarm.

        A 0.3% relative delta in Click Quality (noise threshold 4%) is within noise.
        The delta guard should allow false alarm classification.
        """
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P2",
                "relative_delta_pct": -0.3,  # 0.3% < 4% noise threshold
                "direction": "down",
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 40.0,
                         "baseline_mean": 0.28, "current_mean": 0.279},
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 5.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": False,
        }
        result = run_diagnosis(
            decomposition=decomposition,
            co_movement_result={"likely_cause": "unknown_pattern", "is_positive": False},
        )
        # Should be classified as false alarm — delta is within noise
        assert result["primary_hypothesis"]["archetype"] == "false_alarm"
        assert result["aggregate"].get("severity") == "normal"


class TestHaltBlocksFalseAlarmHighConfidence:
    """Test that a HALT check prevents false alarm → High confidence override."""

    def test_halt_prevents_inferred_false_alarm_high_confidence(self):
        """HALT check + INFERRED false alarm (path b) → confidence NOT overridden to High.

        When a logging artifact is detected (HALT) AND the false alarm was
        inferred (not confirmed by co-movement), we can't trust the data
        enough to say "I'm highly confident this is noise."

        Note: co-movement-confirmed false alarms (path a) CAN still override
        to High even with HALTs, because the multi-metric signal is strong.
        """
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P2",
                "relative_delta_pct": -0.2,  # Within noise → path (b) triggers
                "direction": "down",
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 30.0,
                         "baseline_mean": 0.28, "current_mean": 0.279},
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 0.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": False,
        }
        # Force a HALT via step-change detection + use unknown_pattern (path b)
        step_change = {"detected": True, "change_day_index": 2, "magnitude_pct": 3.0}
        result = run_diagnosis(
            decomposition=decomposition,
            step_change_result=step_change,
            co_movement_result={"likely_cause": "unknown_pattern", "is_positive": False},
        )
        # Confidence should NOT be overridden to High because HALT + path (b)
        assert result["confidence"]["level"] != "High"


class TestMixShiftArchetypeActivation:
    """Test that the mix_shift archetype activates correctly."""

    def test_mix_shift_archetype_activates(self):
        """Check #4 INVESTIGATE + unknown_pattern → mix_shift archetype.

        When co-movement doesn't match a known pattern but mix-shift is
        >= 30%, the movement is likely compositional. The mix_shift
        archetype should be assigned.
        """
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P1",
                "relative_delta_pct": -3.5,
                "direction": "down",
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 70.0,
                         "baseline_mean": 0.28, "current_mean": 0.270},
                    ]
                }
            },
            # Mix-shift >= 30% triggers INVESTIGATE on Check #4
            "mix_shift": {"mix_shift_contribution_pct": 45.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        result = run_diagnosis(
            decomposition=decomposition,
            co_movement_result={"likely_cause": "unknown_pattern", "is_positive": False},
        )
        # Should activate mix_shift archetype
        assert result["primary_hypothesis"]["archetype"] == "mix_shift"
        assert result["primary_hypothesis"]["category"] == "mix_shift"
        # Description should mention composition/mix-shift
        desc = result["primary_hypothesis"]["description"].lower()
        assert "composition" in desc or "mix" in desc

    def test_mix_shift_overrides_no_significant_movement(self):
        """High mix-shift should not be framed as false alarm when co-movement is stable."""
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P2",
                "relative_delta_pct": -0.9,
                "direction": "down",
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {
                            "segment_value": "standard",
                            "contribution_pct": 62.0,
                            "baseline_mean": 0.245,
                            "current_mean": 0.244,
                        },
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 60.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        result = run_diagnosis(
            decomposition=decomposition,
            co_movement_result={"likely_cause": "no_significant_movement", "is_positive": True},
        )
        assert result["primary_hypothesis"]["archetype"] == "mix_shift"
        assert result["primary_hypothesis"]["category"] == "mix_shift"
        assert result["primary_hypothesis"]["archetype"] != "false_alarm"
        desc = result["primary_hypothesis"]["description"].lower()
        assert "compositional" in desc or "mix-shift" in desc or "mix shift" in desc

    def test_mix_shift_clear_signal_not_forced_to_low_confidence(self):
        """Diagnosed mix-shift with clear compositional evidence should be >= Medium."""
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P2",
                "relative_delta_pct": -0.9,
                "direction": "down",
            },
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {
                            "segment_value": "standard",
                            "contribution_pct": 65.0,
                            "baseline_mean": 0.247,
                            "current_mean": 0.246,
                        },
                    ]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 60.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        result = run_diagnosis(
            decomposition=decomposition,
            step_change_result={"detected": True, "change_day_index": 2, "magnitude_pct": 3.0},
            co_movement_result={"likely_cause": "no_significant_movement", "is_positive": True},
        )
        assert result["decision_status"] == "diagnosed"
        assert result["primary_hypothesis"]["archetype"] == "mix_shift"
        assert result["confidence"]["level"] in {"Medium", "High"}


class TestGetTopSegmentContributionDirect:
    """Unit test for _get_top_segment_contribution helper (previously untested)."""

    def test_returns_highest_contribution(self):
        """Should return the absolute contribution of the largest segment."""
        decomp = {
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": 60.0},
                        {"segment_value": "premium", "contribution_pct": -30.0},
                    ]
                },
                "ai_enablement": {
                    "segments": [
                        {"segment_value": "ai_on", "contribution_pct": 45.0},
                    ]
                },
            }
        }
        assert _get_top_segment_contribution(decomp) == 60.0

    def test_empty_breakdown_returns_zero(self):
        """No dimensional data → 0.0."""
        assert _get_top_segment_contribution({"dimensional_breakdown": {}}) == 0.0

    def test_handles_negative_contributions(self):
        """Should use absolute values when comparing."""
        decomp = {
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "standard", "contribution_pct": -80.0},
                    ]
                },
            }
        }
        assert _get_top_segment_contribution(decomp) == 80.0


class TestMultiCauseSuppressionSmart:
    """Test smart multi-cause suppression for ai_adoption archetype."""

    def test_multi_cause_kept_for_unrelated_dimensions(self):
        """ai_adoption + dimensions {ai_enablement, connector_type} → NOT suppressed.

        When the two causes come from dimensions that are NOT correlated
        (ai_enablement and connector_type), multi-cause should be kept.
        """
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P1",
                "direction": "down",
            },
            "dimensional_breakdown": {
                "ai_enablement": {
                    "segments": [
                        {"segment_value": "ai_on", "contribution_pct": 55.0,
                         "baseline_mean": 0.28, "current_mean": 0.24},
                    ]
                },
                "connector_type": {
                    "segments": [
                        {"segment_value": "slack", "contribution_pct": 40.0,
                         "baseline_mean": 0.28, "current_mean": 0.25},
                    ]
                },
            },
            "mix_shift": {"mix_shift_contribution_pct": 5.0},
            "dominant_dimension": "ai_enablement",
            "drill_down_recommended": True,
        }
        co_movement = {"likely_cause": "ai_answers_working", "is_positive": True}
        result = run_diagnosis(
            decomposition=decomposition,
            co_movement_result=co_movement,
        )
        # Multi-cause should be present because dimensions are NOT correlated
        hypothesis = result["primary_hypothesis"]
        assert hypothesis.get("multi_cause") is not None, \
            "Multi-cause should NOT be suppressed for unrelated dimensions"

    def test_multi_cause_suppressed_for_correlated_dimensions(self):
        """ai_adoption + dimensions {ai_enablement, tenant_tier} → suppressed.

        When the two causes are from correlated dimensions, multi-cause
        is just noise — both are proxies for the same AI adoption effect.
        """
        decomposition = {
            "aggregate": {
                "metric": "click_quality_value",
                "severity": "P1",
                "direction": "down",
            },
            "dimensional_breakdown": {
                "ai_enablement": {
                    "segments": [
                        {"segment_value": "ai_on", "contribution_pct": 55.0,
                         "baseline_mean": 0.28, "current_mean": 0.24},
                    ]
                },
                "tenant_tier": {
                    "segments": [
                        {"segment_value": "enterprise", "contribution_pct": 45.0,
                         "baseline_mean": 0.28, "current_mean": 0.25},
                    ]
                },
            },
            "mix_shift": {"mix_shift_contribution_pct": 5.0},
            "dominant_dimension": "ai_enablement",
            "drill_down_recommended": True,
        }
        co_movement = {"likely_cause": "ai_answers_working", "is_positive": True}
        result = run_diagnosis(
            decomposition=decomposition,
            co_movement_result=co_movement,
        )
        # Multi-cause should be suppressed — dimensions are correlated
        hypothesis = result["primary_hypothesis"]
        assert hypothesis.get("multi_cause") is None, \
            "Multi-cause should be suppressed for correlated dimensions"


# ======================================================================
# v1.4: Structured Subagent Specs (confirms_if / rejects_if)
# ======================================================================


class TestArchetypeSubagentSpecs:
    """Validate that every archetype has confirms_if and rejects_if fields.

    v1.4 adds structured verification specs to each archetype for:
    1. verify_diagnosis() coherence checks
    2. Production subagent SQL query generation
    """

    def test_all_archetypes_have_confirms_if(self):
        """Every archetype must have a non-empty confirms_if list."""
        from tools.diagnose import ARCHETYPE_MAP
        for key, val in ARCHETYPE_MAP.items():
            assert "confirms_if" in val, f"{key} missing confirms_if"
            assert isinstance(val["confirms_if"], list), f"{key} confirms_if is not a list"
            assert len(val["confirms_if"]) > 0, f"{key} confirms_if is empty"

    def test_all_archetypes_have_rejects_if(self):
        """Every archetype must have a non-empty rejects_if list."""
        from tools.diagnose import ARCHETYPE_MAP
        for key, val in ARCHETYPE_MAP.items():
            assert "rejects_if" in val, f"{key} missing rejects_if"
            assert isinstance(val["rejects_if"], list), f"{key} rejects_if is not a list"
            assert len(val["rejects_if"]) > 0, f"{key} rejects_if is empty"

    def test_all_archetypes_have_description_template(self):
        """Every archetype must have description_template (bug fix validation).

        The v1.3 query_understanding_regression archetype had summary_template
        instead of description_template, causing silent render failures.
        This test prevents that regression.
        """
        from tools.diagnose import ARCHETYPE_MAP
        for key, val in ARCHETYPE_MAP.items():
            assert "description_template" in val, \
                f"{key} missing description_template (uses wrong key?)"

    def test_all_archetypes_have_action_items(self):
        """Every archetype must have action_items (list, may be empty for false alarm)."""
        from tools.diagnose import ARCHETYPE_MAP
        for key, val in ARCHETYPE_MAP.items():
            assert "action_items" in val, \
                f"{key} missing action_items (uses wrong key?)"
            assert isinstance(val["action_items"], list), \
                f"{key} action_items is not a list"

    def test_confirms_and_rejects_are_strings(self):
        """Each entry in confirms_if and rejects_if must be a string."""
        from tools.diagnose import ARCHETYPE_MAP
        for key, val in ARCHETYPE_MAP.items():
            for i, item in enumerate(val["confirms_if"]):
                assert isinstance(item, str), f"{key}.confirms_if[{i}] is not a string"
            for i, item in enumerate(val["rejects_if"]):
                assert isinstance(item, str), f"{key}.rejects_if[{i}] is not a string"


# ======================================================================
# v1.4: verify_diagnosis() Coherence Checks
# ======================================================================


class TestVerifyDiagnosis:
    """Test the v1.4 post-diagnosis verification checks.

    verify_diagnosis() runs 5 coherence checks on the completed diagnosis
    and returns a list of warnings. Empty list = fully coherent.
    """

    def _make_diagnosis(self, **overrides) -> dict:
        """Helper to build a minimal coherent diagnosis dict for testing."""
        base = {
            "aggregate": {"severity": "P1", "metric": "click_quality_value"},
            "primary_hypothesis": {
                "archetype": "ranking_regression",
                "dimension": "tenant_tier",
                "segment": "standard",
                "contribution_pct": 85.0,
                "is_positive": False,
            },
            "confidence": {"level": "Medium", "reasoning": "test"},
            "validation_checks": [
                {"check": "logging_artifact", "status": "PASS"},
                {"check": "decomposition_completeness", "status": "PASS"},
                {"check": "temporal_consistency", "status": "PASS"},
                {"check": "mix_shift", "status": "PASS"},
            ],
            "action_items": [
                {"action": "Check ranking model deploys", "owner": "Search Ranking team"},
            ],
        }
        # Apply overrides by merging into nested dicts
        for key, value in overrides.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key].update(value)
            else:
                base[key] = value
        return base

    # ── Check 1: Archetype-segment consistency ──

    def test_check1_fires_ai_adoption_wrong_segment(self):
        """ai_adoption archetype with non-ai_enablement top segment → warning."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "ai_adoption",
                "dimension": "tenant_tier",
                "segment": "standard",
                "is_positive": True,
            },
        )
        warnings = verify_diagnosis(diag)
        archetype_warnings = [w for w in warnings if w["check"] == "archetype_segment_consistency"]
        assert len(archetype_warnings) == 1
        assert "ai_adoption" in archetype_warnings[0]["detail"]

    def test_check1_no_fire_ai_adoption_correct_segment(self):
        """ai_adoption archetype with ai_enablement top segment → no warning."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "ai_adoption",
                "dimension": "ai_enablement",
                "segment": "ai_on",
                "is_positive": True,
            },
        )
        warnings = verify_diagnosis(diag)
        archetype_warnings = [w for w in warnings if w["check"] == "archetype_segment_consistency"]
        assert len(archetype_warnings) == 0

    def test_check1_fires_ranking_regression_ai_segment(self):
        """ranking_regression with ai_enablement=ai_on → warning."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "ranking_regression",
                "dimension": "ai_enablement",
                "segment": "ai_on",
                "is_positive": False,
            },
        )
        warnings = verify_diagnosis(diag)
        archetype_warnings = [w for w in warnings if w["check"] == "archetype_segment_consistency"]
        assert len(archetype_warnings) == 1
        assert "ranking_regression" in archetype_warnings[0]["detail"]

    # ── Check 2: Severity-action consistency ──

    def test_check2_fires_p0_no_actions(self):
        """P0 severity with empty action_items → error."""
        diag = self._make_diagnosis(
            aggregate={"severity": "P0"},
            action_items=[],
        )
        warnings = verify_diagnosis(diag)
        severity_warnings = [w for w in warnings if w["check"] == "severity_action_consistency"]
        assert len(severity_warnings) == 1
        assert severity_warnings[0]["severity"] == "error"

    def test_check2_fires_normal_with_actions(self):
        """'normal' severity with action items → warning."""
        diag = self._make_diagnosis(
            aggregate={"severity": "normal"},
            action_items=[{"action": "something", "owner": "someone"}],
        )
        warnings = verify_diagnosis(diag)
        severity_warnings = [w for w in warnings if w["check"] == "severity_action_consistency"]
        assert len(severity_warnings) == 1
        assert severity_warnings[0]["severity"] == "warning"

    def test_check2_no_fire_p1_with_actions(self):
        """P1 severity with action items → no warning (expected)."""
        diag = self._make_diagnosis()  # default has P1 + actions
        warnings = verify_diagnosis(diag)
        severity_warnings = [w for w in warnings if w["check"] == "severity_action_consistency"]
        assert len(severity_warnings) == 0

    # ── Check 3: Confidence-check consistency ──

    def test_check3_fires_high_confidence_with_halt(self):
        """High confidence + HALT check + non-false_alarm → warning."""
        diag = self._make_diagnosis(
            confidence={"level": "High", "reasoning": "test"},
            validation_checks=[
                {"check": "logging_artifact", "status": "HALT"},
                {"check": "decomposition_completeness", "status": "PASS"},
                {"check": "temporal_consistency", "status": "PASS"},
                {"check": "mix_shift", "status": "PASS"},
            ],
        )
        warnings = verify_diagnosis(diag)
        conf_warnings = [w for w in warnings if w["check"] == "confidence_check_consistency"]
        assert len(conf_warnings) == 1

    def test_check3_no_fire_false_alarm_with_halt(self):
        """High confidence + HALT + false_alarm archetype → no warning (allowed)."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "false_alarm",
                "dimension": None,
                "segment": None,
                "is_positive": True,
            },
            confidence={"level": "High", "reasoning": "test"},
            validation_checks=[
                {"check": "logging_artifact", "status": "HALT"},
                {"check": "decomposition_completeness", "status": "PASS"},
                {"check": "temporal_consistency", "status": "PASS"},
                {"check": "mix_shift", "status": "PASS"},
            ],
            aggregate={"severity": "normal"},
            action_items=[],
        )
        warnings = verify_diagnosis(diag)
        conf_warnings = [w for w in warnings if w["check"] == "confidence_check_consistency"]
        assert len(conf_warnings) == 0

    # ── Check 4: False-alarm coherence ──

    def test_check4_fires_false_alarm_with_actions(self):
        """false_alarm archetype with non-empty action_items → error."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "false_alarm",
                "dimension": None,
                "segment": None,
                "is_positive": True,
            },
            aggregate={"severity": "normal"},
            action_items=[{"action": "something", "owner": "someone"}],
        )
        warnings = verify_diagnosis(diag)
        fa_warnings = [w for w in warnings if w["check"] == "false_alarm_coherence"]
        assert any(w["severity"] == "error" for w in fa_warnings)

    def test_check4_fires_false_alarm_not_positive(self):
        """false_alarm with is_positive=False → error."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "false_alarm",
                "dimension": None,
                "segment": None,
                "is_positive": False,
            },
            aggregate={"severity": "normal"},
            action_items=[],
        )
        warnings = verify_diagnosis(diag)
        fa_warnings = [w for w in warnings if w["check"] == "false_alarm_coherence"]
        assert len(fa_warnings) == 1
        assert "is_positive" in fa_warnings[0]["detail"]

    def test_check4_no_fire_coherent_false_alarm(self):
        """Coherent false alarm (empty actions, is_positive=True) → no warning."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "false_alarm",
                "dimension": None,
                "segment": None,
                "is_positive": True,
            },
            aggregate={"severity": "normal"},
            action_items=[],
        )
        warnings = verify_diagnosis(diag)
        fa_warnings = [w for w in warnings if w["check"] == "false_alarm_coherence"]
        assert len(fa_warnings) == 0

    # ── Check 5: Multi-cause-confidence consistency ──

    def test_check5_fires_multi_cause_high_confidence(self):
        """Multi-cause + High confidence → warning."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "ranking_regression",
                "dimension": "tenant_tier",
                "segment": "standard",
                "is_positive": False,
                "multi_cause": [
                    {"dimension": "tenant_tier", "segment": "standard", "contribution_pct": 55},
                    {"dimension": "connector_type", "segment": "slack", "contribution_pct": 40},
                ],
            },
            confidence={"level": "High", "reasoning": "test"},
        )
        warnings = verify_diagnosis(diag)
        mc_warnings = [w for w in warnings if w["check"] == "multi_cause_confidence_consistency"]
        assert len(mc_warnings) == 1

    def test_check5_no_fire_multi_cause_medium_confidence(self):
        """Multi-cause + Medium confidence → no warning (already downgraded)."""
        diag = self._make_diagnosis(
            primary_hypothesis={
                "archetype": "ranking_regression",
                "dimension": "tenant_tier",
                "segment": "standard",
                "is_positive": False,
                "multi_cause": [
                    {"dimension": "tenant_tier", "segment": "standard", "contribution_pct": 55},
                    {"dimension": "connector_type", "segment": "slack", "contribution_pct": 40},
                ],
            },
        )
        warnings = verify_diagnosis(diag)
        mc_warnings = [w for w in warnings if w["check"] == "multi_cause_confidence_consistency"]
        assert len(mc_warnings) == 0

    # ── Integration: coherent diagnosis produces zero warnings ──

    def test_coherent_diagnosis_zero_warnings(self):
        """A well-formed diagnosis should produce zero verification warnings."""
        diag = self._make_diagnosis()
        warnings = verify_diagnosis(diag)
        assert warnings == [], f"Expected zero warnings, got: {warnings}"

    # ── Integration: run_diagnosis includes verification_warnings ──

    def test_run_diagnosis_includes_verification_warnings(self):
        """run_diagnosis() output should include verification_warnings key."""
        decomposition = {
            "aggregate": {"severity": "P1", "metric": "click_quality_value", "direction": "down"},
            "dimensional_breakdown": {
                "tenant_tier": {
                    "segments": [{"segment_value": "standard", "contribution_pct": 85.0,
                                  "baseline_mean": 0.28, "current_mean": 0.245}]
                }
            },
            "mix_shift": {"mix_shift_contribution_pct": 5.0},
            "dominant_dimension": "tenant_tier",
            "drill_down_recommended": True,
        }
        result = run_diagnosis(decomposition=decomposition)
        assert "verification_warnings" in result
        assert isinstance(result["verification_warnings"], list)
