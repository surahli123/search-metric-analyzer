"""Tests for question parser — classifies free-text questions into structured briefs.

Covers:
- extract_metric_hints: metric name extraction from text
- extract_time_range: time range signal extraction
- classify_question_type: 6-type classification
- build_complexity_signals: explainable complexity signals
- parse_question: full end-to-end parsing
- Edge cases: empty input, ambiguous questions, multi-metric questions
- Trace emission: verify spans are emitted with correct metadata
"""

import pytest

from harness.question_parser import (
    extract_metric_hints,
    extract_time_range,
    classify_question_type,
    build_complexity_signals,
    parse_question,
    METRIC_ALIASES,
    CLASSIFICATION_PATTERNS,
    INVESTIGATION_PLANS,
)


# =============================================================================
# extract_metric_hints tests
# =============================================================================

class TestExtractMetricHints:
    """Tests for metric name extraction from question text."""

    def test_single_canonical_name(self):
        """Canonical metric name is extracted."""
        hints = extract_metric_hints("Click Quality dropped 3%")
        assert "click_quality" in hints

    def test_abbreviation_cq(self):
        """CQ abbreviation maps to click_quality."""
        hints = extract_metric_hints("CQ is down")
        assert "click_quality" in hints

    def test_abbreviation_sqs(self):
        """SQS abbreviation maps to search_quality_success."""
        hints = extract_metric_hints("SQS trending up")
        assert "search_quality_success" in hints

    def test_legacy_name_dlctr(self):
        """Legacy name dlctr maps to click_quality."""
        hints = extract_metric_hints("dlctr dropped overnight")
        assert "click_quality" in hints

    def test_multiple_metrics(self):
        """Multiple metrics extracted from one question."""
        hints = extract_metric_hints("CQ dropped but AI trigger is up and AI success improved")
        assert "click_quality" in hints
        assert "ai_trigger" in hints
        assert "ai_success" in hints

    def test_deduplicated(self):
        """Same metric mentioned twice returns one entry."""
        hints = extract_metric_hints("Click Quality and CQ are the same metric")
        assert hints.count("click_quality") == 1

    def test_no_metrics(self):
        """Question with no metric references returns empty list."""
        hints = extract_metric_hints("What tables are available?")
        assert hints == []

    def test_case_insensitive(self):
        """Metric extraction is case-insensitive."""
        hints = extract_metric_hints("CLICK QUALITY dropped")
        assert "click_quality" in hints

    def test_zero_result_rate(self):
        """ZRR abbreviation works."""
        hints = extract_metric_hints("ZRR spiked to 15%")
        assert "zero_result_rate" in hints

    def test_latency_via_p99(self):
        """P99 maps to latency."""
        hints = extract_metric_hints("P99 latency is over 500ms")
        assert "latency" in hints

    def test_phrase_with_spaces(self):
        """Multi-word metric names with spaces are matched."""
        hints = extract_metric_hints("search quality success is stable")
        assert "search_quality_success" in hints


# =============================================================================
# extract_time_range tests
# =============================================================================

class TestExtractTimeRange:
    """Tests for time range signal extraction."""

    def test_wow(self):
        """Week-over-week signal detected."""
        result = extract_time_range("CQ dropped 3% WoW")
        assert result["type"] == "wow"

    def test_week_over_week_spelled_out(self):
        result = extract_time_range("week over week comparison")
        assert result["type"] == "wow"

    def test_mom(self):
        """Month-over-month signal detected."""
        result = extract_time_range("Trend analysis MoM")
        assert result["type"] == "mom"

    def test_qoq(self):
        """Quarter-over-quarter signal detected."""
        result = extract_time_range("How did Q1 compare QoQ?")
        assert result["type"] == "qoq"

    def test_explicit_dates(self):
        """Explicit ISO dates extracted."""
        result = extract_time_range("Compare 2026-03-01 to 2026-03-15")
        assert result["type"] == "custom"
        assert result["start"] == "2026-03-01"
        assert result["end"] == "2026-03-15"

    def test_single_date(self):
        """Single date with no end date."""
        result = extract_time_range("What happened on 2026-03-10?")
        assert result["type"] == "custom"
        assert result["start"] == "2026-03-10"

    def test_default_wow(self):
        """No time signal defaults to WoW."""
        result = extract_time_range("CQ dropped")
        assert result["type"] == "wow"

    def test_last_week(self):
        result = extract_time_range("What happened last week?")
        assert result["type"] == "wow"

    def test_last_month(self):
        result = extract_time_range("What happened last month?")
        assert result["type"] == "mom"


# =============================================================================
# classify_question_type tests
# =============================================================================

class TestClassifyQuestionType:
    """Tests for question type classification."""

    def test_sev_question(self):
        q_type, _ = classify_question_type("Click Quality dropped 6.2% overnight")
        assert q_type == "sev"

    def test_sev_with_p0(self):
        q_type, _ = classify_question_type("P0: CQ crashed")
        assert q_type == "sev"

    def test_experiment_question(self):
        q_type, _ = classify_question_type("Is the experiment showing significance?")
        assert q_type == "experiment"

    def test_ab_test(self):
        q_type, _ = classify_question_type("How is the A/B test performing?")
        assert q_type == "experiment"

    def test_trend_question(self):
        q_type, _ = classify_question_type("How has CQ trended over time this quarter?")
        assert q_type == "trend"

    def test_deep_dive(self):
        q_type, _ = classify_question_type("Investigate the root cause of this drop")
        assert q_type == "deep_dive"

    def test_system_understanding(self):
        q_type, _ = classify_question_type("What is the relationship between AI adoption and CQ?")
        assert q_type == "system_understanding"

    def test_adhoc_formula(self):
        q_type, _ = classify_question_type("What is the Click Quality formula?")
        assert q_type == "adhoc"

    def test_adhoc_definition(self):
        q_type, _ = classify_question_type("What's the definition of SQS?")
        assert q_type == "adhoc"

    def test_adhoc_explain(self):
        q_type, _ = classify_question_type("Explain the AI adoption trap")
        assert q_type == "adhoc"

    def test_empty_question_defaults_to_adhoc(self):
        """Empty question defaults to adhoc (lowest-risk mode)."""
        q_type, _ = classify_question_type("")
        assert q_type == "adhoc"

    def test_ambiguous_question_uses_priority(self):
        """When multiple patterns match equally, priority breaks the tie."""
        # "dropped" matches sev (priority 1), "investigate" matches deep_dive (priority 4)
        # sev should win because it has higher priority (lower number)
        q_type, _ = classify_question_type("dropped — investigate this")
        assert q_type == "sev"

    def test_returns_matched_keywords(self):
        """Matched keywords are returned for explainability."""
        _, matches = classify_question_type("CQ dropped overnight and spiked back up")
        assert len(matches) > 0
        assert any(kw in matches for kw in ["dropped", "overnight", "spiked"])


# =============================================================================
# build_complexity_signals tests
# =============================================================================

class TestBuildComplexitySignals:
    """Tests for complexity signal generation."""

    def test_multiple_metrics_signal(self):
        signals = build_complexity_signals("sev", ["click_quality", "ai_trigger"], "CQ and AI trigger")
        assert any("multiple_metrics" in s for s in signals)

    def test_p0_severity_signal(self):
        signals = build_complexity_signals("sev", ["click_quality"], "P0 CQ crash")
        assert "P0_severity" in signals

    def test_p1_severity_signal(self):
        signals = build_complexity_signals("sev", ["click_quality"], "P1 CQ drop")
        assert "P1_severity" in signals

    def test_type_complexity_included(self):
        signals = build_complexity_signals("sev", ["click_quality"], "CQ dropped")
        assert "diagnostic" in signals

    def test_adhoc_complexity(self):
        signals = build_complexity_signals("adhoc", [], "What is CQ?")
        assert "simple_lookup" in signals

    def test_cross_metric_analysis(self):
        signals = build_complexity_signals(
            "system_understanding", ["click_quality", "ai_trigger"],
            "What is the relationship between CQ and AI trigger?"
        )
        assert "cross_metric_analysis" in signals


# =============================================================================
# parse_question end-to-end tests
# =============================================================================

class TestParseQuestion:
    """End-to-end tests for the full question parsing pipeline."""

    def test_sev_question_full_parse(self):
        """SEV question produces correct QuestionBrief."""
        brief = parse_question("Click Quality dropped 6.2% overnight")
        assert brief["question_type"] == "sev"
        assert "click_quality" in brief["metric_hints"]
        assert brief["raw_question"] == "Click Quality dropped 6.2% overnight"
        assert len(brief["investigation_plan"]) > 0
        assert len(brief["complexity_signals"]) > 0

    def test_adhoc_question_full_parse(self):
        """Adhoc question produces minimal brief."""
        brief = parse_question("What is the Click Quality formula?")
        assert brief["question_type"] == "adhoc"
        assert "click_quality" in brief["metric_hints"]
        assert "simple_lookup" in brief["complexity_signals"]

    def test_multi_metric_sev(self):
        """Multi-metric SEV question extracts all metrics."""
        brief = parse_question("CQ dropped and SQS is down — P0 incident")
        assert brief["question_type"] == "sev"
        assert "click_quality" in brief["metric_hints"]
        assert "search_quality_success" in brief["metric_hints"]

    def test_experiment_with_time_range(self):
        """Experiment question with explicit time range."""
        brief = parse_question("Is the A/B test from 2026-03-01 to 2026-03-15 significant?")
        assert brief["question_type"] == "experiment"
        assert brief["time_range_hints"]["type"] == "custom"
        assert brief["time_range_hints"]["start"] == "2026-03-01"

    def test_investigation_plan_matches_type(self):
        """Investigation plan is appropriate for the question type."""
        brief = parse_question("Click Quality dropped 6.2% overnight")
        assert brief["investigation_plan"] == INVESTIGATION_PLANS["sev"]

    def test_empty_question(self):
        """Empty question doesn't crash — produces adhoc brief."""
        brief = parse_question("")
        assert brief["question_type"] == "adhoc"
        assert brief["metric_hints"] == []

    def test_trace_emission(self):
        """Trace span is emitted when trace is provided."""
        from trace.collector import InvestigationTrace
        trace = InvestigationTrace(question="test")
        brief = parse_question("CQ dropped 3%", trace=trace)
        # Verify span was emitted by checking trace spans
        trace_dict = trace.to_dict()
        spans = trace_dict.get("spans", [])
        assert len(spans) > 0
        # Find the question_classification span
        classification_spans = [
            s for s in spans if s.get("decision") == "question_classification"
        ]
        assert len(classification_spans) == 1
        assert classification_spans[0]["value"] == "sev"

    def test_no_trace_doesnt_crash(self):
        """parse_question works fine without a trace (trace=None)."""
        brief = parse_question("CQ dropped 3%")
        assert brief["question_type"] == "sev"


# =============================================================================
# Edge cases
# =============================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_unicode_question(self):
        """Unicode characters don't crash the parser."""
        brief = parse_question("CQ dropped — is this a résumé of failures?")
        assert brief["question_type"] == "sev"

    def test_very_long_question(self):
        """Very long questions don't crash."""
        long_q = "Click Quality dropped " + "and more details " * 100
        brief = parse_question(long_q)
        assert brief["question_type"] == "sev"

    def test_only_metric_no_action(self):
        """Question with metric name but no action verb defaults to adhoc."""
        brief = parse_question("click_quality")
        # No action keywords → falls back to adhoc
        assert brief["question_type"] == "adhoc"
        assert "click_quality" in brief["metric_hints"]

    def test_all_investigation_plans_exist(self):
        """Every question type has an investigation plan."""
        for pattern in CLASSIFICATION_PATTERNS:
            q_type = pattern["type"]
            assert q_type in INVESTIGATION_PLANS, f"Missing plan for {q_type}"
