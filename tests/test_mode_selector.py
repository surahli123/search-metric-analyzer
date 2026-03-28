"""Tests for mode selector — routes questions to Simple/Medium/Complex investigation modes.

Covers:
- All 9 routing rules (adhoc→Simple, sev+P0→Complex, etc.)
- Override mechanism
- Invalid override handling
- Trace emission
- Mode definitions (agent_file, stages, token budgets)
- Edge cases
"""

import pytest

from harness.mode_selector import (
    select_mode,
    MODES,
    _apply_routing_rules,
    _has_severity_signal,
    _has_multiple_metrics,
)


# =============================================================================
# Fixtures — common QuestionBrief dicts
# =============================================================================

@pytest.fixture
def adhoc_brief():
    return {
        "question_type": "adhoc",
        "metric_hints": ["click_quality"],
        "complexity_signals": ["simple_lookup"],
    }


@pytest.fixture
def sev_p0_brief():
    return {
        "question_type": "sev",
        "metric_hints": ["click_quality"],
        "complexity_signals": ["P0_severity", "diagnostic"],
    }


@pytest.fixture
def sev_p1_brief():
    return {
        "question_type": "sev",
        "metric_hints": ["click_quality"],
        "complexity_signals": ["P1_severity", "diagnostic"],
    }


@pytest.fixture
def sev_p2_brief():
    return {
        "question_type": "sev",
        "metric_hints": ["click_quality"],
        "complexity_signals": ["diagnostic"],
    }


@pytest.fixture
def experiment_single_brief():
    return {
        "question_type": "experiment",
        "metric_hints": ["click_quality"],
        "complexity_signals": ["evaluation"],
    }


@pytest.fixture
def experiment_multi_brief():
    return {
        "question_type": "experiment",
        "metric_hints": ["click_quality", "ai_trigger"],
        "complexity_signals": ["multiple_metrics (2 found)", "evaluation"],
    }


@pytest.fixture
def deep_dive_brief():
    return {
        "question_type": "deep_dive",
        "metric_hints": ["click_quality"],
        "complexity_signals": ["comprehensive"],
    }


@pytest.fixture
def trend_brief():
    return {
        "question_type": "trend",
        "metric_hints": ["click_quality"],
        "complexity_signals": ["longitudinal"],
    }


@pytest.fixture
def system_understanding_brief():
    return {
        "question_type": "system_understanding",
        "metric_hints": ["click_quality", "ai_trigger"],
        "complexity_signals": ["cross_metric_analysis", "analytical"],
    }


# =============================================================================
# Routing rule tests
# =============================================================================

class TestRoutingRules:
    """Test each of the 9 routing rules."""

    def test_rule1_adhoc_to_simple(self, adhoc_brief):
        """Rule 1: adhoc → Simple."""
        decision = select_mode(adhoc_brief)
        assert decision["mode"] == "simple"
        assert decision["confidence"] >= 0.9

    def test_rule2_sev_p0_to_complex(self, sev_p0_brief):
        """Rule 2: sev + P0 → Complex."""
        decision = select_mode(sev_p0_brief)
        assert decision["mode"] == "complex"
        assert "P0" in decision["reasoning"] or "critical" in decision["reasoning"]

    def test_rule2b_sev_p1_to_complex(self, sev_p1_brief):
        """Rule 2b: sev + P1 → Complex."""
        decision = select_mode(sev_p1_brief)
        assert decision["mode"] == "complex"

    def test_rule3_sev_p2_to_medium(self, sev_p2_brief):
        """Rule 3: sev + P2/normal → Medium."""
        decision = select_mode(sev_p2_brief)
        assert decision["mode"] == "medium"

    def test_rule4_experiment_multi_metric_to_complex(self, experiment_multi_brief):
        """Rule 4: experiment + multiple metrics → Complex."""
        decision = select_mode(experiment_multi_brief)
        assert decision["mode"] == "complex"
        assert "multiple metrics" in decision["reasoning"].lower() or "interaction" in decision["reasoning"].lower()

    def test_rule5_experiment_single_to_medium(self, experiment_single_brief):
        """Rule 5: experiment (single metric) → Medium."""
        decision = select_mode(experiment_single_brief)
        assert decision["mode"] == "medium"

    def test_rule6_deep_dive_to_complex(self, deep_dive_brief):
        """Rule 6: deep_dive → Complex (always)."""
        decision = select_mode(deep_dive_brief)
        assert decision["mode"] == "complex"
        assert decision["confidence"] >= 0.9

    def test_rule7_trend_to_medium(self, trend_brief):
        """Rule 7: trend → Medium."""
        decision = select_mode(trend_brief)
        assert decision["mode"] == "medium"

    def test_rule8_system_understanding_to_medium(self, system_understanding_brief):
        """Rule 8: system_understanding → Medium."""
        decision = select_mode(system_understanding_brief)
        assert decision["mode"] == "medium"

    def test_rule9_unknown_type_to_medium(self):
        """Rule 9: unknown type → Medium (safe default)."""
        brief = {
            "question_type": "some_future_type",
            "metric_hints": ["click_quality"],
            "complexity_signals": [],
        }
        decision = select_mode(brief)
        assert decision["mode"] == "medium"
        assert decision["confidence"] < 0.7  # Low confidence for fallback


# =============================================================================
# Override tests
# =============================================================================

class TestOverride:
    """Test the manual mode override mechanism."""

    def test_override_simple(self, sev_p0_brief):
        """Override forces simple mode even for P0 sev."""
        decision = select_mode(sev_p0_brief, override_mode="simple")
        assert decision["mode"] == "simple"
        assert decision["confidence"] == 1.0
        assert "override" in decision["reasoning"].lower()

    def test_override_complex(self, adhoc_brief):
        """Override forces complex mode even for adhoc."""
        decision = select_mode(adhoc_brief, override_mode="complex")
        assert decision["mode"] == "complex"
        assert decision["confidence"] == 1.0

    def test_invalid_override_falls_back(self, sev_p0_brief):
        """Invalid override falls back to medium with warning."""
        decision = select_mode(sev_p0_brief, override_mode="banana")
        assert decision["mode"] == "medium"
        assert decision["confidence"] == 0.5
        assert "invalid" in decision["reasoning"].lower()


# =============================================================================
# Decision output tests
# =============================================================================

class TestDecisionOutput:
    """Test the ModeDecision dict structure."""

    def test_decision_has_all_fields(self, adhoc_brief):
        decision = select_mode(adhoc_brief)
        assert "mode" in decision
        assert "confidence" in decision
        assert "reasoning" in decision
        assert "agent_file" in decision

    def test_agent_file_matches_mode(self, adhoc_brief):
        decision = select_mode(adhoc_brief)
        assert decision["agent_file"] == MODES["simple"]["agent_file"]

    def test_complex_agent_file(self, sev_p0_brief):
        decision = select_mode(sev_p0_brief)
        assert decision["agent_file"] == MODES["complex"]["agent_file"]

    def test_confidence_between_0_and_1(self, sev_p0_brief):
        decision = select_mode(sev_p0_brief)
        assert 0.0 <= decision["confidence"] <= 1.0


# =============================================================================
# Trace emission tests
# =============================================================================

class TestTraceEmission:
    """Test trace span emission."""

    def test_trace_emitted(self, adhoc_brief):
        from trace.collector import InvestigationTrace
        trace = InvestigationTrace(question="test")
        select_mode(adhoc_brief, trace=trace)
        trace_dict = trace.to_dict()
        spans = trace_dict.get("spans", [])
        mode_spans = [s for s in spans if s.get("decision") == "mode_selection"]
        assert len(mode_spans) == 1
        assert mode_spans[0]["value"] == "simple"

    def test_no_trace_doesnt_crash(self, adhoc_brief):
        """select_mode works without a trace."""
        decision = select_mode(adhoc_brief)
        assert decision["mode"] == "simple"


# =============================================================================
# Mode definitions tests
# =============================================================================

class TestModeDefinitions:
    """Test that MODES dict is well-formed."""

    def test_three_modes_defined(self):
        assert len(MODES) == 3
        assert "simple" in MODES
        assert "medium" in MODES
        assert "complex" in MODES

    def test_all_modes_have_agent_file(self):
        for mode, info in MODES.items():
            assert "agent_file" in info, f"{mode} missing agent_file"
            assert info["agent_file"].startswith("domains/search_metrics/agents/")

    def test_simple_has_no_stages(self):
        assert MODES["simple"]["stages"] == []

    def test_medium_has_4_stages(self):
        assert len(MODES["medium"]["stages"]) == 4

    def test_complex_has_4_stages(self):
        assert len(MODES["complex"]["stages"]) == 4

    def test_token_budgets_increase_with_complexity(self):
        assert MODES["simple"]["max_tokens"] < MODES["medium"]["max_tokens"]
        assert MODES["medium"]["max_tokens"] < MODES["complex"]["max_tokens"]


# =============================================================================
# Helper function tests
# =============================================================================

class TestHelpers:
    """Test internal helper functions."""

    def test_has_severity_signal_p0(self):
        brief = {"complexity_signals": ["P0_severity", "diagnostic"]}
        assert _has_severity_signal(brief, {"p0"}) is True

    def test_has_severity_signal_none(self):
        brief = {"complexity_signals": ["diagnostic"]}
        assert _has_severity_signal(brief, {"p0"}) is False

    def test_has_multiple_metrics_true(self):
        brief = {"metric_hints": ["click_quality", "ai_trigger"]}
        assert _has_multiple_metrics(brief) is True

    def test_has_multiple_metrics_false(self):
        brief = {"metric_hints": ["click_quality"]}
        assert _has_multiple_metrics(brief) is False

    def test_has_multiple_metrics_empty(self):
        brief = {"metric_hints": []}
        assert _has_multiple_metrics(brief) is False
