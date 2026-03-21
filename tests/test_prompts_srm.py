"""TDD tests for SRM prompt integration — verifies the dispatch prompt
tells the LLM about the srm_check field so rule_srm_check can fire.

The critical gap: rule_srm_check in seam_validator.py expects
finding["srm_check"]["expected_ratio"] and finding["srm_check"]["actual_ratio"],
but the dispatch prompt never told the LLM to produce this field.
These tests verify the fix.
"""

import pytest

from harness.prompts import build_dispatch_system_prompt


class TestDispatchPromptSRMField:
    """Verify the dispatch system prompt includes srm_check field spec."""

    def test_prompt_mentions_srm_check_field(self):
        """The prompt must tell the LLM that srm_check is a valid output field."""
        prompt = build_dispatch_system_prompt()
        assert "srm_check" in prompt, (
            "Dispatch prompt must mention 'srm_check' field — without it, "
            "the LLM will never produce SRM data and rule_srm_check is a no-op"
        )

    def test_prompt_specifies_expected_ratio(self):
        """The prompt must tell the LLM to include expected_ratio in srm_check.

        rule_srm_check reads finding["srm_check"]["expected_ratio"] and
        defaults to 0.5 if missing. The prompt should mention this field
        so the LLM produces it explicitly.
        """
        prompt = build_dispatch_system_prompt()
        assert "expected_ratio" in prompt, (
            "Dispatch prompt must mention 'expected_ratio' — "
            "rule_srm_check reads this field from the finding"
        )

    def test_prompt_specifies_actual_ratio(self):
        """The prompt must tell the LLM to include actual_ratio in srm_check.

        rule_srm_check reads finding["srm_check"]["actual_ratio"] and
        computes deviation from expected. Without actual_ratio, the check
        is skipped (actual_ratio is None → no comparison made).
        """
        prompt = build_dispatch_system_prompt()
        assert "actual_ratio" in prompt, (
            "Dispatch prompt must mention 'actual_ratio' — "
            "rule_srm_check needs this to compute deviation"
        )

    def test_srm_check_marked_as_optional(self):
        """srm_check should be optional — only relevant for experiment hypotheses.

        Non-experiment findings shouldn't be penalized for missing this field.
        The prompt should say 'optional' to avoid LLM hallucinating SRM data
        for non-experiment investigations.
        """
        prompt = build_dispatch_system_prompt()
        assert "optional" in prompt.lower(), (
            "srm_check must be marked optional in the prompt — "
            "it only applies to experiment investigations"
        )

    def test_srm_check_mentions_experiment_context(self):
        """The prompt should explain when to include srm_check
        (only for experiment/A/B test hypotheses)."""
        prompt = build_dispatch_system_prompt()
        assert "experiment" in prompt.lower(), (
            "Prompt should mention 'experiment' context for srm_check"
        )


class TestSRMCheckEndToEnd:
    """Verify the full chain: prompt → LLM output → rule_srm_check fires."""

    def test_rule_srm_check_fires_with_matching_finding(self):
        """If an LLM produces srm_check data matching the prompt spec,
        rule_srm_check should detect an imbalanced experiment."""
        from contracts.seam_validator import rule_srm_check

        # Simulate an LLM finding that followed the prompt's srm_check spec
        finding_with_srm = {
            "findings": [{
                "agent_name": "llm_investigator",
                "hypothesis_id": "hyp_001",
                "verdict": "confirmed",
                "confidence": 0.85,
                "evidence": [{"metric": "click_quality", "value": 0.22}],
                "narrative": "Experiment shows significant effect",
                "srm_check": {
                    "expected_ratio": 0.5,
                    "actual_ratio": 0.55,  # 5% deviation → SRM!
                },
            }],
        }

        result = rule_srm_check(finding_with_srm, question_type="experiment")
        assert result is not None, (
            "rule_srm_check should fire when finding has srm_check with "
            "actual_ratio deviating >1% from expected_ratio"
        )
        assert "SRM detected" in result

    def test_rule_srm_check_passes_balanced_experiment(self):
        """Balanced experiment (within 1% deviation) should pass."""
        from contracts.seam_validator import rule_srm_check

        finding_balanced = {
            "findings": [{
                "srm_check": {
                    "expected_ratio": 0.5,
                    "actual_ratio": 0.505,  # 0.5% deviation → OK
                },
            }],
        }

        result = rule_srm_check(finding_balanced, question_type="experiment")
        assert result is None, "Balanced experiment should pass SRM check"

    def test_rule_srm_check_skips_non_experiment(self):
        """Non-experiment investigations should skip SRM check entirely."""
        from contracts.seam_validator import rule_srm_check

        finding_with_srm = {
            "findings": [{
                "srm_check": {
                    "expected_ratio": 0.5,
                    "actual_ratio": 0.8,  # Huge deviation but irrelevant
                },
            }],
        }

        result = rule_srm_check(finding_with_srm, question_type="sev")
        assert result is None, "Non-experiment should skip SRM check"
