"""Tests for validation checks and confidence scoring."""

import pytest
from tools.diagnose import (
    check_logging_artifact,
    check_decomposition_completeness,
    check_temporal_consistency,
    check_mix_shift_threshold,
    compute_confidence,
    run_diagnosis,
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
        decomp = run_decomposition(sample_metric_rows, "dlctr_value",
                                   dimensions=["tenant_tier"])
        result = run_diagnosis(decomposition=decomp)
        assert "confidence" in result
        assert "validation_checks" in result
        assert result["confidence"]["level"] in ["High", "Medium", "Low"]

    def test_includes_all_4_checks(self, sample_metric_rows):
        from tools.decompose import run_decomposition
        decomp = run_decomposition(sample_metric_rows, "dlctr_value",
                                   dimensions=["tenant_tier"])
        result = run_diagnosis(decomposition=decomp)
        check_names = [c["check"] for c in result["validation_checks"]]
        assert "logging_artifact" in check_names
        assert "decomposition_completeness" in check_names
        assert "temporal_consistency" in check_names
        assert "mix_shift" in check_names
