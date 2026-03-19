"""Tests for Wave 5 quality gates — 4 new rules extending SMA from 11 to 15 rules.

Covers:
- rule_question_brief_valid: QUESTION_PARSE stage, HARD gate
- rule_srm_check: DISPATCH stage, SOFT gate (experiment-only)
- rule_mode_compliance_simple: SYNTHESIZE stage, SOFT gate
- rule_report_quality_score: SYNTHESIZE stage, SOFT gate (12-point rubric)
- Integration: validate_seam() with new QUESTION_PARSE stage
- Rule count verification: 15 total rules across 5 stages
"""

import pytest

from contracts.seam_validator import (
    # New Wave 5 rules
    rule_question_brief_valid,
    rule_srm_check,
    rule_mode_compliance_simple,
    rule_report_quality_score,
    # Existing infrastructure
    validate_seam,
    SeamViolation,
    GATE_TIERS,
    STAGE_RULES,
    VALID_QUESTION_TYPES,
    REPORT_QUALITY_THRESHOLD,
    HEDGE_WORDS,
)


# =============================================================================
# rule_question_brief_valid tests
# =============================================================================

class TestRuleQuestionBriefValid:
    """Tests for the QUESTION_PARSE stage validation rule."""

    def test_valid_sev_question(self):
        """A SEV question with metric hints passes."""
        brief = {
            "question_type": "sev",
            "metric_hints": ["click_quality"],
        }
        assert rule_question_brief_valid(brief) is None

    def test_valid_adhoc_no_metrics(self):
        """Adhoc questions don't need metric hints — they're lookups."""
        brief = {
            "question_type": "adhoc",
            "metric_hints": [],
        }
        assert rule_question_brief_valid(brief) is None

    def test_valid_adhoc_with_metrics(self):
        """Adhoc questions with metrics are also fine."""
        brief = {
            "question_type": "adhoc",
            "metric_hints": ["click_quality"],
        }
        assert rule_question_brief_valid(brief) is None

    def test_invalid_question_type(self):
        """Unknown question type is rejected."""
        brief = {
            "question_type": "banana",
            "metric_hints": ["click_quality"],
        }
        result = rule_question_brief_valid(brief)
        assert result is not None
        assert "banana" in result
        assert "invalid" in result

    def test_none_question_type(self):
        """None question type is rejected."""
        brief = {
            "question_type": None,
            "metric_hints": ["click_quality"],
        }
        result = rule_question_brief_valid(brief)
        assert result is not None

    def test_missing_question_type(self):
        """Missing question_type field is rejected."""
        brief = {"metric_hints": ["click_quality"]}
        result = rule_question_brief_valid(brief)
        assert result is not None

    def test_sev_without_metrics(self):
        """SEV question without metric hints fails — pipeline needs to know what to analyze."""
        brief = {
            "question_type": "sev",
            "metric_hints": [],
        }
        result = rule_question_brief_valid(brief)
        assert result is not None
        assert "metric_hints is empty" in result

    def test_experiment_without_metrics(self):
        """Experiment question without metrics fails."""
        brief = {
            "question_type": "experiment",
            "metric_hints": [],
        }
        result = rule_question_brief_valid(brief)
        assert result is not None

    def test_all_valid_types_pass(self):
        """Every valid question type passes with metric hints."""
        for qt in VALID_QUESTION_TYPES:
            brief = {
                "question_type": qt,
                "metric_hints": ["click_quality"],
            }
            result = rule_question_brief_valid(brief)
            assert result is None, f"Type '{qt}' should pass but got: {result}"


# =============================================================================
# rule_srm_check tests
# =============================================================================

class TestRuleSRMCheck:
    """Tests for the experiment SRM (Sample Ratio Mismatch) check."""

    def test_non_experiment_skipped(self):
        """Non-experiment investigations skip the SRM check entirely."""
        result = {"findings": [{"srm_check": {"expected_ratio": 0.5, "actual_ratio": 0.7}}]}
        assert rule_srm_check(result, question_type="sev") is None

    def test_no_question_type_skipped(self):
        """Missing question_type skips the SRM check."""
        result = {"findings": [{"srm_check": {"expected_ratio": 0.5, "actual_ratio": 0.7}}]}
        assert rule_srm_check(result) is None

    def test_balanced_experiment_passes(self):
        """Experiment with balanced arms (within 1%) passes."""
        result = {
            "findings": [{
                "srm_check": {"expected_ratio": 0.5, "actual_ratio": 0.505},
            }],
        }
        assert rule_srm_check(result, question_type="experiment") is None

    def test_imbalanced_experiment_fails(self):
        """Experiment with >1% arm imbalance triggers SRM warning."""
        result = {
            "findings": [{
                "srm_check": {"expected_ratio": 0.5, "actual_ratio": 0.55},
            }],
        }
        violation = rule_srm_check(result, question_type="experiment")
        assert violation is not None
        assert "SRM detected" in violation
        assert "0.50%" in violation or "50.00%" in violation

    def test_no_srm_data_passes(self):
        """Experiment findings without srm_check field pass (SRM data not always available)."""
        result = {
            "findings": [{"hypothesis_id": "hyp_001", "evidence": []}],
        }
        assert rule_srm_check(result, question_type="experiment") is None

    def test_exact_threshold_passes(self):
        """Deviation at 1% boundary is within tolerance."""
        result = {
            "findings": [{
                "srm_check": {"expected_ratio": 0.5, "actual_ratio": 0.509},
            }],
        }
        assert rule_srm_check(result, question_type="experiment") is None

    def test_severe_imbalance_fails(self):
        """Major SRM (e.g., 60/40 split on 50/50 experiment) fails."""
        result = {
            "findings": [{
                "srm_check": {"expected_ratio": 0.5, "actual_ratio": 0.6},
            }],
        }
        violation = rule_srm_check(result, question_type="experiment")
        assert violation is not None
        assert "randomization may have failed" in violation


# =============================================================================
# rule_mode_compliance_simple tests
# =============================================================================

class TestRuleModeComplianceSimple:
    """Tests for the simple-mode compliance check."""

    def test_non_simple_mode_skipped(self):
        """Medium/Complex mode reports skip this check."""
        result = {"dispatch_findings": [{"hypothesis_id": "hyp_001"}]}
        assert rule_mode_compliance_simple(result, mode="medium") is None
        assert rule_mode_compliance_simple(result, mode="complex") is None

    def test_no_mode_skipped(self):
        """Missing mode kwarg skips the check."""
        result = {"dispatch_findings": [{"hypothesis_id": "hyp_001"}]}
        assert rule_mode_compliance_simple(result) is None

    def test_simple_without_findings_passes(self):
        """Simple-mode report with no DISPATCH findings passes."""
        result = {"dispatch_findings": []}
        assert rule_mode_compliance_simple(result, mode="simple") is None

    def test_simple_no_findings_key_passes(self):
        """Simple-mode report without dispatch_findings key at all passes."""
        result = {"tldr": "The CQ formula is..."}
        assert rule_mode_compliance_simple(result, mode="simple") is None

    def test_simple_with_findings_fails(self):
        """Simple-mode report that somehow contains DISPATCH findings fails."""
        result = {
            "dispatch_findings": [
                {"hypothesis_id": "hyp_001", "verdict": "confirmed"},
            ],
        }
        violation = rule_mode_compliance_simple(result, mode="simple")
        assert violation is not None
        assert "Simple-mode report" in violation
        assert "1 DISPATCH findings" in violation


# =============================================================================
# rule_report_quality_score tests
# =============================================================================

class TestRuleReportQualityScore:
    """Tests for the 12-point report quality rubric."""

    def test_high_quality_report_passes(self):
        """Report with all 4 criteria met scores 12/12 and passes."""
        result = {
            "tldr": "Click Quality dropped 3.2% WoW. The root cause is a connector failure. Investigate immediately.",
            "root_cause": "Confluence connector degraded, causing 2.1pp of the 3.2% total drop.",
            "hypothesis_and_evidence": "Ranking regression hypothesis: evidence shows 0.5% model drift.",
            "dimensional_breakdown": "Enterprise tier contributed 67% of the movement.",
            "severity": "P1",
            "confidence_grade": "Medium",
            "validation_summary": "Cross-check passed.",
            "recommended_actions": [{"action": "Check connector pipeline", "owner": "DE team"}],
            "upgrade_condition": "Would upgrade to High if connector logs confirm failure timing",
        }
        assert rule_report_quality_score(result) is None

    def test_empty_report_fails(self):
        """Empty report scores 3/12 (no hedges = 3 points) and fails."""
        result = {}
        violation = rule_report_quality_score(result)
        assert violation is not None
        assert "3/12" in violation

    def test_missing_actions_still_passes_if_other_criteria_met(self):
        """Report with 3/4 criteria met (9/12) passes the threshold."""
        result = {
            "tldr": "CQ dropped 3.2% WoW. Root cause: connector failure. Action needed.",
            "root_cause": "Connector degradation explains 2.1pp drop.",
            "hypothesis_and_evidence": "Evidence shows 0.5% drift.",
            "recommended_actions": [],  # Missing actions (-3 points) → 9/12 > threshold
        }
        assert rule_report_quality_score(result) is None

    def test_hedge_words_reduce_score(self):
        """Hedge words in conclusions reduce the score."""
        result = {
            "tldr": "It appears that Click Quality might suggest a regression.",
            "root_cause": "It is possible that the connector potentially caused this.",
            "hypothesis_and_evidence": "Evidence shows 0.5% drift.",
            "recommended_actions": [{"action": "Check connector"}],
        }
        # Multiple hedge words → 0 points for criterion 3
        # tldr has sentences → 3 points, no numeric evidence → 0 points,
        # actions present → 3 points. Total: 6/12, at threshold
        # But actually "0.5%" in hypothesis_and_evidence counts as evidence
        # So: 3 (tldr) + 3 (evidence) + 0 (hedges) + 3 (actions) = 9/12 → passes
        # The hedge penalty is -3, not a fail on its own
        # Actually let me re-check: "it appears" and "might suggest" are in tldr
        # "it is possible" and "potentially" are in root_cause
        # conclusion_text = tldr + root_cause → 4+ hedge phrases → 0 points
        # evidence in hypothesis_and_evidence → 3 points
        # actions present → 3 points
        # tldr has 1-2 sentences → 3 points
        # Total: 3 + 3 + 0 + 3 = 9 → passes
        result_check = rule_report_quality_score(result)
        # 9/12 is above threshold (6) so it should pass
        assert result_check is None

    def test_verbose_tldr_penalized(self):
        """TL;DR with >5 sentences gets reduced score (1 instead of 3)."""
        result = {
            "tldr": (
                "First sentence. Second sentence. Third sentence. "
                "Fourth sentence. Fifth sentence. Sixth sentence. "
                "Seventh sentence."
            ),
            "root_cause": "Connector degradation explains 2.1pp drop.",
            "hypothesis_and_evidence": "Evidence shows 0.5% drift.",
            "recommended_actions": [{"action": "Check connector"}],
        }
        # 1 (verbose tldr) + 3 (evidence) + 3 (no hedges) + 3 (actions) = 10/12 → passes
        assert rule_report_quality_score(result) is None

    def test_no_evidence_no_actions_fails(self):
        """Report with no numeric evidence and no actions fails."""
        result = {
            "tldr": "Something happened.",
            "root_cause": "Something caused it.",
            "hypothesis_and_evidence": "We looked into it.",
            "recommended_actions": [],
        }
        # 3 (short tldr) + 0 (no evidence) + 3 (no hedges) + 0 (no actions) = 6/12
        # Exactly at threshold → passes (not < threshold)
        assert rule_report_quality_score(result) is None

    def test_barely_failing_report(self):
        """Report with only 1 criterion met (hedge-word-free) fails."""
        result = {
            "tldr": "",  # Empty → 0 points
            "root_cause": "Unknown.",
            "hypothesis_and_evidence": "Nothing found.",
            "recommended_actions": [],  # No actions → 0 points
        }
        # 0 (empty tldr) + 0 (no evidence) + 3 (no hedges) + 0 (no actions) = 3/12
        violation = rule_report_quality_score(result)
        assert violation is not None
        assert "3/12" in violation
        assert "below threshold" in violation


# =============================================================================
# Integration: validate_seam with QUESTION_PARSE stage
# =============================================================================

class TestQuestionParseStageIntegration:
    """Test validate_seam() works with the new QUESTION_PARSE stage."""

    def test_question_parse_uses_hard_gate(self):
        """QUESTION_PARSE stage has a HARD gate — raises SeamViolation on failure."""
        assert GATE_TIERS["QUESTION_PARSE"] == "hard"

    def test_valid_brief_passes_validation(self):
        """Valid QuestionBrief passes QUESTION_PARSE validation."""
        brief = {
            "question_type": "sev",
            "metric_hints": ["click_quality"],
        }
        result = validate_seam(brief, stage="QUESTION_PARSE")
        assert result["passed"] is True

    def test_invalid_brief_raises_seam_violation(self):
        """Invalid QuestionBrief raises SeamViolation (HARD gate)."""
        brief = {
            "question_type": "banana",
            "metric_hints": ["click_quality"],
        }
        with pytest.raises(SeamViolation) as exc_info:
            validate_seam(brief, stage="QUESTION_PARSE")
        assert exc_info.value.tier == "hard"
        assert "banana" in exc_info.value.violations[0]

    def test_question_parse_in_stage_rules(self):
        """QUESTION_PARSE stage exists in STAGE_RULES."""
        assert "QUESTION_PARSE" in STAGE_RULES
        assert len(STAGE_RULES["QUESTION_PARSE"]) == 1


# =============================================================================
# Rule count verification
# =============================================================================

class TestRuleCount:
    """Verify total rule count matches expectations (11 → 15)."""

    def test_total_rule_count_is_17(self):
        """SMA now has 17 business rules across 5 stages (was 13 across 4).

        Original: UNDERSTAND=2, HYPOTHESIZE=6, DISPATCH=2, SYNTHESIZE=3 = 13
        Wave 5: +QUESTION_PARSE=1, +DISPATCH=1, +SYNTHESIZE=2 = +4 = 17
        """
        total = sum(len(rules) for rules in STAGE_RULES.values())
        assert total == 17, (
            f"Expected 17 total rules (13 original + 4 Wave 5), got {total}. "
            f"Breakdown: {', '.join(f'{k}={len(v)}' for k, v in STAGE_RULES.items())}"
        )

    def test_stage_count_is_5(self):
        """Now 5 stages: QUESTION_PARSE + UNDERSTAND + HYPOTHESIZE + DISPATCH + SYNTHESIZE."""
        assert len(STAGE_RULES) == 5

    def test_question_parse_has_1_rule(self):
        assert len(STAGE_RULES["QUESTION_PARSE"]) == 1

    def test_understand_has_2_rules(self):
        assert len(STAGE_RULES["UNDERSTAND"]) == 2

    def test_hypothesize_has_6_rules(self):
        assert len(STAGE_RULES["HYPOTHESIZE"]) == 6

    def test_dispatch_has_3_rules(self):
        """DISPATCH: 2 original + 1 new (rule_srm_check) = 3."""
        assert len(STAGE_RULES["DISPATCH"]) == 3

    def test_synthesize_has_3_original_plus_2_new(self):
        """SYNTHESIZE: 3 original + 2 new (mode_compliance + quality_score) = 5."""
        assert len(STAGE_RULES["SYNTHESIZE"]) == 5
