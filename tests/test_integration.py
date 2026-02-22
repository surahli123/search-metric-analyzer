#!/usr/bin/env python3
"""End-to-end integration test: synthetic data -> decompose -> diagnose -> format.

This is the final quality gate before v1-alpha. It verifies that the full
diagnostic pipeline works end-to-end for 3+ scenario types:

1. Single-cause regression (standard tier Click Quality drop)
2. Mix-shift composition change (no behavioral regression)
3. False alarm / stable baseline (no significant movement)

Each test runs the complete pipeline:
  raw rows -> decompose -> diagnose -> format -> validate output

These tests use the shared fixtures from conftest.py so we don't duplicate
test data. They verify OUTPUT QUALITY, not just that the code runs:
- Does the diagnosis find the right root cause?
- Is the confidence level appropriate?
- Does the Slack message have a TL;DR?
- Is everything JSON-serializable for Claude Code?
"""

import json
import pytest
from tools.decompose import run_decomposition
from tools.anomaly import detect_step_change, check_data_quality
from tools.diagnose import run_diagnosis
from tools.formatter import format_diagnosis_output, generate_slack_message


# ──────────────────────────────────────────────────
# Scenario 1: Single-Cause Regression
# Uses sample_metric_rows from conftest.py
# Expected: Click Quality drop concentrated in standard tier
# ──────────────────────────────────────────────────

class TestSingleCauseRegression:
    """Full pipeline test for a clean, single-cause ranking regression."""

    def test_full_pipeline_produces_slack_and_report(self, sample_metric_rows):
        """End-to-end: decompose -> diagnose -> format -> output."""
        # Step 1: Decompose by tenant_tier
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        assert decomp["aggregate"]["error"] is None

        # Step 2: Diagnose
        diagnosis = run_diagnosis(decomposition=decomp)
        assert diagnosis["confidence"]["level"] in ["High", "Medium", "Low"]

        # Step 3: Format
        output = format_diagnosis_output(diagnosis)
        assert "slack_message" in output
        assert "short_report" in output
        assert len(output["slack_message"]) > 50  # not empty
        assert "TL;DR" in output["slack_message"] or "Summary" in output["short_report"]

    def test_identifies_standard_tier_as_dominant(self, sample_metric_rows):
        """The pipeline should find that standard tier drives the drop."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)

        # Primary hypothesis should point to tenant_tier
        hypothesis = diagnosis["primary_hypothesis"]
        assert hypothesis["dimension"] == "tenant_tier"
        assert hypothesis["segment"] == "standard"
        # Standard tier should contribute the majority of the drop
        assert hypothesis["contribution_pct"] > 50

    def test_confidence_is_not_low(self, sample_metric_rows):
        """Clean single-cause signal should not produce Low confidence."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)

        # With a clean signal, confidence should be Medium or High
        assert diagnosis["confidence"]["level"] in ["Medium", "High"]

    def test_validation_checks_run(self, sample_metric_rows):
        """All 4 validation checks should be present in the output."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)

        checks = diagnosis["validation_checks"]
        assert len(checks) == 4
        check_names = {c["check"] for c in checks}
        assert check_names == {
            "logging_artifact",
            "decomposition_completeness",
            "temporal_consistency",
            "mix_shift",
        }

    def test_action_items_not_empty(self, sample_metric_rows):
        """A real regression should produce at least one action item."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)

        assert len(diagnosis["action_items"]) >= 1

    def test_output_is_json_serializable(self, sample_metric_rows):
        """Everything must be JSON-serializable for Claude Code to read."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)

        # Must not raise
        json_str = json.dumps(output)
        assert json_str is not None

        # Also verify the diagnosis itself is serializable
        diag_str = json.dumps(diagnosis)
        assert diag_str is not None


# ──────────────────────────────────────────────────
# Scenario 2: Mix-Shift (Composition Change)
# Uses sample_mix_shift_rows from conftest.py
# Expected: aggregate drops but per-segment Click Quality is stable
# ──────────────────────────────────────────────────

class TestMixShiftScenario:
    """Full pipeline test for a mix-shift scenario (no behavioral regression)."""

    def test_detects_mix_shift(self, sample_mix_shift_rows):
        """Mix-shift analysis should flag significant composition change."""
        decomp = run_decomposition(
            sample_mix_shift_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )

        # Mix-shift should be detected
        mix_shift = decomp.get("mix_shift", {})
        mix_pct = mix_shift.get("mix_shift_contribution_pct", 0)
        # In our fixture, per-segment Click Quality is identical between periods,
        # so 100% of the aggregate change is mix-shift
        assert mix_pct > 30, (
            f"Mix-shift should be >30% for pure composition change, got {mix_pct}%"
        )

    def test_mix_shift_check_flags_investigate(self, sample_mix_shift_rows):
        """Diagnosis should flag mix-shift for investigation."""
        decomp = run_decomposition(
            sample_mix_shift_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)

        # The mix_shift validation check should say INVESTIGATE
        mix_check = next(
            (c for c in diagnosis["validation_checks"] if c["check"] == "mix_shift"),
            None
        )
        assert mix_check is not None
        assert mix_check["status"] == "INVESTIGATE", (
            f"Mix-shift check should be INVESTIGATE, got {mix_check['status']}"
        )

    def test_full_pipeline_with_mix_shift(self, sample_mix_shift_rows):
        """End-to-end pipeline should produce valid output for mix-shift."""
        decomp = run_decomposition(
            sample_mix_shift_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)

        # Output should mention mix-shift in the report
        report = output["short_report"].lower()
        assert "mix" in report, "Report should mention mix-shift"

        # Should be JSON-serializable
        json.dumps(output)


# ──────────────────────────────────────────────────
# Scenario 3: False Alarm / Stable Baseline
# Generates inline rows with no significant movement
# Expected: tool says "no action needed"
# ──────────────────────────────────────────────────

class TestFalseAlarmScenario:
    """Full pipeline test for a stable metric (no real movement)."""

    @pytest.fixture
    def stable_rows(self):
        """Rows where Click Quality is essentially flat between periods.

        Tiny random variation (<0.5%) that should NOT trigger an alert.
        """
        rows = []
        for i in range(20):
            rows.append({
                "period": "baseline",
                "tenant_tier": "standard" if i % 2 == 0 else "premium",
                "click_quality_value": 0.280,
                "search_quality_success_value": 0.378,
            })
        for i in range(20):
            # Tiny variation: 0.280 -> 0.279 (-0.36%), well within normal
            rows.append({
                "period": "current",
                "tenant_tier": "standard" if i % 2 == 0 else "premium",
                "click_quality_value": 0.279,
                "search_quality_success_value": 0.377,
            })
        return rows

    def test_stable_metric_low_severity(self, stable_rows):
        """A flat metric should get low severity (P2 or normal)."""
        decomp = run_decomposition(
            stable_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )

        # Delta should be tiny
        aggregate = decomp["aggregate"]
        assert abs(aggregate["relative_delta_pct"]) < 2.0, (
            f"Stable metric should have <2% delta, got {aggregate['relative_delta_pct']}%"
        )
        # Severity should be P2 or normal (not P0/P1)
        assert aggregate["severity"] in ("P2", "normal"), (
            f"Stable metric should be P2 or normal, got {aggregate['severity']}"
        )

    def test_full_pipeline_stable_produces_output(self, stable_rows):
        """Even for a non-event, the pipeline should produce valid output."""
        decomp = run_decomposition(
            stable_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)

        assert "slack_message" in output
        assert "short_report" in output
        assert len(output["slack_message"]) > 20

        # Should be JSON-serializable
        json.dumps(output)


# ──────────────────────────────────────────────────
# Cross-Scenario: Anti-Pattern Checks
# ──────────────────────────────────────────────────

class TestAntiPatterns:
    """Verify output quality across scenarios — no hedging, no data dumps."""

    def test_slack_message_has_tldr(self, sample_metric_rows):
        """Every Slack message must start with or contain a TL;DR."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        slack_msg = generate_slack_message(diagnosis)

        assert "TL;DR" in slack_msg or "tl;dr" in slack_msg.lower(), (
            "Slack message must contain TL;DR"
        )

    def test_slack_message_not_too_long(self, sample_metric_rows):
        """Slack message should be 5-15 non-empty lines (scannable)."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        slack_msg = generate_slack_message(diagnosis)

        # Count non-empty lines
        non_empty = [line for line in slack_msg.split("\n") if line.strip()]
        assert len(non_empty) >= 5, f"Slack message too short: {len(non_empty)} lines"
        assert len(non_empty) <= 20, f"Slack message too long: {len(non_empty)} lines"

    def test_report_has_all_sections(self, sample_metric_rows):
        """Short report should contain all required sections."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)
        report = output["short_report"]

        required_sections = [
            "Summary",
            "Decomposition",
            "Diagnosis",
            "Validation Checks",
            "Business Impact",
            "Recommended Actions",
            "What Would Change",
        ]
        for section in required_sections:
            assert section in report, f"Report missing section: {section}"

    def test_no_hedging_language(self, sample_metric_rows):
        """Output should not contain hedging anti-patterns."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)

        combined = output["slack_message"] + output["short_report"]
        hedging_terms = ["it's unclear", "we're not sure", "hard to say"]
        for term in hedging_terms:
            assert term not in combined.lower(), (
                f"Output contains hedging language: '{term}'"
            )

    def test_confidence_explicitly_stated(self, sample_metric_rows):
        """Output must state confidence level explicitly."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)

        # Confidence should appear in both outputs
        assert "confidence" in output["slack_message"].lower()
        assert "Confidence" in output["short_report"]


# ──────────────────────────────────────────────────
# Pipeline Stage Compatibility
# ──────────────────────────────────────────────────

class TestPipelineStageCompatibility:
    """Verify that each stage's output is compatible with the next stage's input."""

    def test_decompose_output_feeds_into_diagnose(self, sample_metric_rows):
        """decompose output should be directly usable as diagnose input."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        # This should not raise — output format compatibility
        diagnosis = run_diagnosis(decomposition=decomp)
        assert "confidence" in diagnosis
        assert "primary_hypothesis" in diagnosis

    def test_diagnose_output_feeds_into_formatter(self, sample_metric_rows):
        """diagnose output should be directly usable as formatter input."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        # This should not raise — output format compatibility
        output = format_diagnosis_output(diagnosis)
        assert isinstance(output["slack_message"], str)
        assert isinstance(output["short_report"], str)

    def test_multi_dimension_decomposition(self, sample_metric_rows):
        """Pipeline should work with multiple decomposition dimensions."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier", "ai_enablement"]
        )
        diagnosis = run_diagnosis(decomposition=decomp)
        output = format_diagnosis_output(diagnosis)

        # Both dimensions should appear in the breakdown
        assert "tenant_tier" in decomp["dimensional_breakdown"]
        assert "ai_enablement" in decomp["dimensional_breakdown"]

        # Formatter should handle multi-dimension output
        assert len(output["short_report"]) > 100

    def test_anomaly_detection_feeds_into_diagnose(self, sample_metric_rows):
        """anomaly.detect_step_change output feeds into diagnose as step_change_result."""
        decomp = run_decomposition(
            sample_metric_rows, "click_quality_value",
            dimensions=["tenant_tier"]
        )

        # Run anomaly detection
        values = [r["click_quality_value"] for r in sample_metric_rows]
        step_result = detect_step_change(values)

        # Feed both into diagnose
        diagnosis = run_diagnosis(
            decomposition=decomp,
            step_change_result=step_result,
        )
        assert "validation_checks" in diagnosis
        # The logging_artifact check should reflect step_change_result
        logging_check = next(
            c for c in diagnosis["validation_checks"]
            if c["check"] == "logging_artifact"
        )
        assert logging_check["status"] in ("PASS", "HALT")
