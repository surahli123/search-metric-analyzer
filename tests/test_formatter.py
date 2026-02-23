"""Tests for Slack message and report template generation."""

import pytest
from tools.formatter import (
    generate_slack_message,
    generate_short_report,
    format_diagnosis_output,
)

SAMPLE_DIAGNOSIS = {
    "aggregate": {
        "metric": "dlctr_value",
        "baseline_mean": 0.280,
        "current_mean": 0.2625,
        "relative_delta_pct": -6.25,
        "direction": "down",
        "severity": "P0",
    },
    "primary_hypothesis": {
        "category": "algorithm_model",
        "description": "Ranking model regression for Standard tier",
    },
    "confidence": {
        "level": "High",
        "reasoning": "Decomposition explains 94%, temporal match confirmed, no contradicting co-movements.",
        "would_upgrade_if": None,
        "would_downgrade_if": "Experiment team reports no model change in this period.",
    },
    "validation_checks": [
        {"check": "logging_artifact", "status": "PASS", "detail": "No overnight step-change detected"},
        {"check": "decomposition_completeness", "status": "PASS", "detail": "94% of drop explained"},
        {"check": "temporal_consistency", "status": "PASS", "detail": "Drop onset matches model deploy"},
        {"check": "mix_shift", "status": "PASS", "detail": "12% mix-shift (below 30% threshold)"},
    ],
    "dimensional_breakdown": {
        "tenant_tier": {
            "segments": [
                {"segment_value": "standard", "contribution_pct": 78.0, "delta": -0.035},
                {"segment_value": "premium", "contribution_pct": 22.0, "delta": -0.005},
            ]
        }
    },
    "mix_shift": {"mix_shift_contribution_pct": 12.0},
    "action_items": [
        {"action": "Check ranking model version deployed this week", "owner": "Ranking team"},
        {"action": "Review Standard tier query performance", "owner": "Search DS"},
    ],
}


class TestSlackMessage:
    def test_has_severity_and_confidence_in_header(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        assert "P0" in msg
        assert "High" in msg

    def test_has_tldr(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        assert "TL;DR" in msg or "tl;dr" in msg.lower()

    def test_has_key_findings(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        assert "finding" in msg.lower() or "%" in msg

    def test_length_is_reasonable(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        lines = [l for l in msg.strip().split("\n") if l.strip()]
        assert 4 <= len(lines) <= 15

    def test_no_anti_patterns(self):
        msg = generate_slack_message(SAMPLE_DIAGNOSIS)
        hedge_phrases = ["it could be", "it might be", "possibly", "perhaps",
                         "further investigation needed", "was impacted by"]
        for phrase in hedge_phrases:
            assert phrase not in msg.lower(), f"Anti-pattern found: '{phrase}'"


class TestShortReport:
    def test_has_all_required_sections(self):
        report = generate_short_report(SAMPLE_DIAGNOSIS)
        required_sections = ["Summary", "Decomposition", "Diagnosis",
                            "Validation", "Business Impact", "Recommended Actions"]
        for section in required_sections:
            assert section.lower() in report.lower(), f"Missing section: {section}"

    def test_has_confidence_upgrade_conditions(self):
        report = generate_short_report(SAMPLE_DIAGNOSIS)
        assert "would" in report.lower()

    def test_has_validation_check_table(self):
        report = generate_short_report(SAMPLE_DIAGNOSIS)
        assert "PASS" in report

    def test_high_mix_shift_frames_compositional_driver(self):
        diagnosis = dict(SAMPLE_DIAGNOSIS)
        diagnosis["mix_shift"] = {"mix_shift_contribution_pct": 60.0}
        diagnosis["primary_hypothesis"] = dict(SAMPLE_DIAGNOSIS["primary_hypothesis"])
        diagnosis["primary_hypothesis"]["description"] = (
            "Traffic composition change (mix-shift) is the primary driver."
        )

        slack = generate_slack_message(diagnosis).lower()
        assert "compositional change dominates" in slack
        assert "behavioral change dominates" not in slack

    def test_blocked_by_data_quality_uses_blocked_severity_language(self):
        diagnosis = dict(SAMPLE_DIAGNOSIS)
        diagnosis["aggregate"] = dict(SAMPLE_DIAGNOSIS["aggregate"])
        diagnosis["aggregate"]["severity"] = "blocked"
        diagnosis["decision_status"] = "blocked_by_data_quality"
        diagnosis["trust_gate_result"] = {
            "status": "fail",
            "reason": "freshness too stale",
        }
        diagnosis["primary_hypothesis"] = {
            "category": "data_quality",
            "archetype": "blocked_by_data_quality",
            "description": "Diagnosis blocked by data quality gate.",
        }
        diagnosis["action_items"] = [
            {
                "action": "Resolve trust-gate failure and rerun diagnosis",
                "owner": "Search Platform team",
            }
        ]

        slack = generate_slack_message(diagnosis).lower()
        report = generate_short_report(diagnosis).lower()

        assert "severity: blocked" in slack
        assert "diagnosis blocked by data quality gate" in slack
        assert "blocked pending data quality recovery" in report


class TestFormatDiagnosisOutput:
    def test_returns_both_formats(self):
        result = format_diagnosis_output(SAMPLE_DIAGNOSIS)
        assert "slack_message" in result
        assert "short_report" in result

    def test_output_is_string(self):
        result = format_diagnosis_output(SAMPLE_DIAGNOSIS)
        assert isinstance(result["slack_message"], str)
        assert isinstance(result["short_report"], str)
