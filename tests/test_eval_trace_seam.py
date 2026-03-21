#!/usr/bin/env python3
"""Tests for Wave 4 eval trace and seam coverage checks.

These checks are INFORMATIONAL (deduction=0) — they report coverage gaps
without penalizing scores. This file tests that the check functions:
1. Return empty when no trace/seam data is present (backward compat)
2. Correctly identify missing IC9 decisions and seam stages
3. Return zero deductions for all issues
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from eval.run_eval import _check_trace_coverage, _check_seam_coverage


# ──────────────────────────────────────────────────
# Trace Coverage Tests
# ──────────────────────────────────────────────────

class TestTraceCoverage:
    """Verify _check_trace_coverage() behavior."""

    def test_returns_empty_when_no_trace(self):
        """No _trace key in diagnosis → skip silently (backward compat)."""
        diagnosis = {"primary_hypothesis": {"description": "test"}}
        result = _check_trace_coverage(diagnosis)
        assert result == []

    def test_reports_missing_decisions(self):
        """Partial trace (only metric_direction) → report other 3 as missing."""
        diagnosis = {
            "_trace": {
                "summary": {
                    "invisible_decisions_traced": ["metric_direction"],
                },
                "spans": [{"stage": "UNDERSTAND"}],
                "seam_validations": [],
            },
        }
        issues = _check_trace_coverage(diagnosis)
        # Should report missing: hypothesis_inclusion, context_construction, narrative_selection
        # Plus missing seam validations and missing spans for stages
        assert len(issues) > 0
        # Check that the IC9 decision issues are present
        issue_reasons = [i["reason"] for i in issues]
        assert any("hypothesis_inclusion" in r for r in issue_reasons)
        assert any("context_construction" in r for r in issue_reasons)
        assert any("narrative_selection" in r for r in issue_reasons)

    def test_all_decisions_traced_no_issues(self):
        """All 4 IC9 decisions traced + all seams + all spans → no issues."""
        diagnosis = {
            "_trace": {
                "summary": {
                    "invisible_decisions_traced": [
                        "metric_direction",
                        "hypothesis_inclusion",
                        "context_construction",
                        "narrative_selection",
                    ],
                },
                "spans": [
                    {"stage": "UNDERSTAND"},
                    {"stage": "HYPOTHESIZE"},
                    {"stage": "DISPATCH"},
                    {"stage": "SYNTHESIZE"},
                ],
                "seam_validations": [
                    {"stage": "UNDERSTAND"},
                    {"stage": "HYPOTHESIZE"},
                    {"stage": "DISPATCH"},
                    {"stage": "SYNTHESIZE"},
                ],
            },
        }
        issues = _check_trace_coverage(diagnosis)
        assert issues == []

    def test_deductions_are_zero(self):
        """All trace coverage issues must have deduction=0 (informational only)."""
        diagnosis = {
            "_trace": {
                "summary": {"invisible_decisions_traced": []},
                "spans": [],
                "seam_validations": [],
            },
        }
        issues = _check_trace_coverage(diagnosis)
        assert len(issues) > 0
        for issue in issues:
            assert issue["deduction"] == 0, (
                f"Trace coverage issue should be informational (deduction=0), "
                f"got deduction={issue['deduction']} for rule={issue['rule']}"
            )


# ──────────────────────────────────────────────────
# Seam Coverage Tests
# ──────────────────────────────────────────────────

class TestSeamCoverage:
    """Verify _check_seam_coverage() behavior."""

    def test_returns_empty_when_no_seam_data(self):
        """No _seam_validations key → skip silently (backward compat)."""
        diagnosis = {"primary_hypothesis": {"description": "test"}}
        result = _check_seam_coverage(diagnosis)
        assert result == []

    def test_reports_missing_stages(self):
        """Only UNDERSTAND validated → report other 3 as missing."""
        diagnosis = {
            "_seam_validations": {
                "UNDERSTAND": {"passed": True, "violations": [], "tier": "hard"},
            },
        }
        issues = _check_seam_coverage(diagnosis)
        assert len(issues) == 3
        missing_stages = {i["rule"] for i in issues}
        assert "seam_missing_hypothesize" in missing_stages
        assert "seam_missing_dispatch" in missing_stages
        assert "seam_missing_synthesize" in missing_stages

    def test_all_stages_validated_no_issues(self):
        """All 4 stages validated → no issues."""
        diagnosis = {
            "_seam_validations": {
                "UNDERSTAND": {"passed": True},
                "HYPOTHESIZE": {"passed": True},
                "DISPATCH": {"passed": True},
                "SYNTHESIZE": {"passed": True},
            },
        }
        issues = _check_seam_coverage(diagnosis)
        assert issues == []

    def test_deductions_are_zero(self):
        """All seam coverage issues must have deduction=0 (informational only)."""
        diagnosis = {"_seam_validations": {}}
        issues = _check_seam_coverage(diagnosis)
        assert len(issues) == 4  # All 4 stages missing
        for issue in issues:
            assert issue["deduction"] == 0, (
                f"Seam coverage issue should be informational (deduction=0), "
                f"got deduction={issue['deduction']} for rule={issue['rule']}"
            )
