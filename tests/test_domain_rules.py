"""Tests for domain-aware seam validation (Wave 7A.2).

Validates that:
1. validate_seam accepts domain_rules parameter
2. domain_rules are run alongside base STAGE_RULES
3. Search-specific rules from domains/search_metrics/rules.py work correctly
4. Rules imported into seam_validator match those in the domain module
"""

import pytest
from contracts.seam_validator import (
    validate_seam,
    STAGE_RULES,
    SeamViolation,
)
from domains.search_metrics.rules import (
    rule_question_brief_valid,
    rule_hypotheses_consistent_with_co_movement,
    rule_mix_shift_considered_when_detected,
    rule_effect_size_proportionality,
    VALID_QUESTION_TYPES,
    SEARCH_METRIC_RULES,
)
from domains.search_metrics import SearchMetricsDomain


# ---------------------------------------------------------------------------
# Verify rules are properly registered
# ---------------------------------------------------------------------------

class TestRuleRegistration:
    """Verify search-specific rules are in both the domain AND seam_validator."""

    def test_question_brief_valid_in_stage_rules(self):
        """rule_question_brief_valid should be in QUESTION_PARSE rules."""
        rule_funcs = STAGE_RULES["QUESTION_PARSE"]
        rule_names = [r.__name__ for r in rule_funcs]
        assert "rule_question_brief_valid" in rule_names

    def test_co_movement_in_stage_rules(self):
        """rule_hypotheses_consistent_with_co_movement should be in HYPOTHESIZE rules."""
        rule_funcs = STAGE_RULES["HYPOTHESIZE"]
        rule_names = [r.__name__ for r in rule_funcs]
        assert "rule_hypotheses_consistent_with_co_movement" in rule_names

    def test_mix_shift_in_stage_rules(self):
        rule_funcs = STAGE_RULES["HYPOTHESIZE"]
        rule_names = [r.__name__ for r in rule_funcs]
        assert "rule_mix_shift_considered_when_detected" in rule_names

    def test_effect_size_in_stage_rules(self):
        rule_funcs = STAGE_RULES["SYNTHESIZE"]
        rule_names = [r.__name__ for r in rule_funcs]
        assert "rule_effect_size_proportionality" in rule_names

    def test_domain_returns_same_rules(self):
        """Domain.get_quality_rules() should reference the same functions."""
        domain = SearchMetricsDomain()
        domain_rules = domain.get_quality_rules()
        domain_checks = {r["check"] for r in domain_rules}

        assert rule_question_brief_valid in domain_checks
        assert rule_hypotheses_consistent_with_co_movement in domain_checks
        assert rule_mix_shift_considered_when_detected in domain_checks
        assert rule_effect_size_proportionality in domain_checks

    def test_search_metric_rules_registry(self):
        """SEARCH_METRIC_RULES should have 4 rules covering 3 stages."""
        assert len(SEARCH_METRIC_RULES) == 4
        stages = {r["stage"] for r in SEARCH_METRIC_RULES}
        assert stages == {"QUESTION_PARSE", "HYPOTHESIZE", "SYNTHESIZE"}


# ---------------------------------------------------------------------------
# domain_rules parameter
# ---------------------------------------------------------------------------

class TestDomainRulesParameter:
    """Test that validate_seam accepts and runs domain_rules."""

    def test_domain_rules_none_is_default(self):
        """With domain_rules=None, behavior is unchanged."""
        result = {"question_type": "sev"}
        validation = validate_seam(result, "QUESTION_PARSE")
        assert validation["passed"] is True

    def test_domain_rules_are_executed(self):
        """Custom domain rules should be run alongside base rules.
        Uses HYPOTHESIZE (SOFT gate) to avoid SeamViolation on failure."""
        def custom_rule(result, **kwargs):
            return "custom violation" if result.get("trigger") else None

        # Provide enough hypotheses to pass generic rules, but trigger custom rule
        result = {
            "trigger": True,
            "hypotheses": [
                {"hypothesis_id": "h1", "confirms_if": ["x"], "is_contrarian": True, "expected_magnitude": "1%"},
                {"hypothesis_id": "h2", "confirms_if": ["y"], "expected_magnitude": "2%"},
                {"hypothesis_id": "h3", "confirms_if": ["z"], "expected_magnitude": "3%"},
            ],
        }
        validation = validate_seam(
            result, "HYPOTHESIZE",
            domain_rules=[custom_rule],
        )
        assert validation["passed"] is False
        assert "custom violation" in validation["violations"]

    def test_domain_rules_dont_replace_base_rules(self):
        """Base rules still run when domain_rules are provided.
        Uses QUESTION_PARSE (HARD gate) — invalid type raises SeamViolation."""
        def harmless_rule(result, **kwargs):
            return None  # Always passes

        result = {"question_type": "INVALID_TYPE"}
        with pytest.raises(SeamViolation):
            validate_seam(
                result, "QUESTION_PARSE",
                domain_rules=[harmless_rule],
            )


# ---------------------------------------------------------------------------
# Individual rule behavior (from domains/search_metrics/rules.py)
# ---------------------------------------------------------------------------

class TestSearchSpecificRules:
    """Test the extracted search-specific rules directly."""

    def test_valid_question_types(self):
        """All 6 search question types should be accepted."""
        for qt in VALID_QUESTION_TYPES:
            assert rule_question_brief_valid({"question_type": qt}) is None

    def test_invalid_question_type(self):
        violation = rule_question_brief_valid({"question_type": "aggregation"})
        assert violation is not None
        assert "invalid" in violation

    def test_co_movement_blocks_non_contrarian(self):
        """AI adoption pattern should block non-contrarian CQ degradation."""
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "click_quality_degradation", "is_contrarian": False}
            ]
        }
        understand = {
            "co_movement_pattern": {"pattern_name": "ai_adoption_expected"}
        }
        violation = rule_hypotheses_consistent_with_co_movement(
            result, understand_result=understand
        )
        assert violation is not None
        assert "ai_adoption_expected" in violation

    def test_co_movement_allows_contrarian(self):
        """Contrarian CQ degradation hypothesis should be allowed."""
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "click_quality_degradation", "is_contrarian": True}
            ]
        }
        understand = {
            "co_movement_pattern": {"pattern_name": "ai_adoption_expected"}
        }
        violation = rule_hypotheses_consistent_with_co_movement(
            result, understand_result=understand
        )
        assert violation is None

    def test_mix_shift_required_when_detected(self):
        """Mix-shift > 25% must produce a mix-shift hypothesis."""
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "ranking_regression"}
            ]
        }
        understand = {
            "mix_shift_result": {"detected": True, "contribution_pct": 0.35}
        }
        violation = rule_mix_shift_considered_when_detected(
            result, understand_result=understand
        )
        assert violation is not None
        assert "mix-shift" in violation.lower() or "Mix-shift" in violation

    def test_mix_shift_satisfied(self):
        result = {
            "hypotheses": [
                {"hypothesis_id": "h1", "archetype": "mix_shift"}
            ]
        }
        understand = {
            "mix_shift_result": {"detected": True, "contribution_pct": 0.35}
        }
        violation = rule_mix_shift_considered_when_detected(
            result, understand_result=understand
        )
        assert violation is None

    def test_effect_size_p0_no_minimizing(self):
        """P0 reports should not use minimizing words."""
        result = {
            "severity": "P0",
            "tldr": "This is a minor issue in the ranking pipeline",
            "root_cause": "Small regression in model accuracy",
        }
        violation = rule_effect_size_proportionality(result)
        assert violation is not None
        assert "minor" in violation or "small" in violation.lower()

    def test_effect_size_p1_allows_minimizing(self):
        """P1 reports can use minimizing words (only P0 is restricted)."""
        result = {
            "severity": "P1",
            "tldr": "Minor regression in click quality",
            "root_cause": "Small model change",
        }
        violation = rule_effect_size_proportionality(result)
        assert violation is None
