"""Tests for the trace module — span creation, collection, serialization, and validation.

Covers:
- TraceSpan and SeamSpan TypedDict creation
- make_span_id() uniqueness and sortability
- InvestigationTrace: emit, emit_seam, filtering, agent_context, roundtrip
- validate_trace_completeness and validate_span_fields from schema.py
"""

import json
import time

import pytest

from trace.span import TraceSpan, SeamSpan, make_span_id
from trace.collector import InvestigationTrace
from trace.schema import (
    IC9_INVISIBLE_DECISIONS,
    REQUIRED_SEAMS,
    validate_trace_completeness,
    validate_span_fields,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def trace():
    """A fresh InvestigationTrace for testing."""
    return InvestigationTrace(question="CQ dropped 6.2% week-over-week")


@pytest.fixture
def sample_span() -> TraceSpan:
    """A minimal valid TraceSpan dict."""
    return TraceSpan(
        trace_id="inv_test123",
        span_id="span_000_abc",
        stage="UNDERSTAND",
        swimlane="deterministic",
        tool="core.anomaly.detect_step_change",
        decision="metric_direction",
        code_enforced=True,
        value="down",
        timestamp_ms=int(time.time() * 1000),
        human_summary="Detected CQ dropped 6.2%",
        agent_context="metric_direction=down, magnitude=6.2%",
    )


def _make_full_trace(trace: InvestigationTrace) -> InvestigationTrace:
    """Populate a trace with all 4 IC9 decisions and all 4 seams for completeness tests."""
    ic9_decisions = [
        ("UNDERSTAND", "metric_direction", "down"),
        ("HYPOTHESIZE", "hypothesis_inclusion", "kept 3 of 5"),
        ("DISPATCH", "context_construction", "full context"),
        ("SYNTHESIZE", "narrative_selection", "ranking regression"),
    ]
    for stage, decision, value in ic9_decisions:
        trace.emit(TraceSpan(
            stage=stage,
            swimlane="deterministic",
            tool=f"core.{stage.lower()}",
            decision=decision,
            value=value,
        ))
    for stage in REQUIRED_SEAMS:
        trace.emit_seam(
            stage=stage,
            schema=f"{stage.title()}Result",
            passed=True,
            tier="hard",
            checks={"rule_1": True},
        )
    return trace


# =============================================================================
# TestMakeSpanId — span ID generation
# =============================================================================

class TestMakeSpanId:
    """Tests for the make_span_id() utility function."""

    def test_starts_with_span_prefix(self):
        """Span IDs should start with 'span_' for easy identification in logs."""
        sid = make_span_id()
        assert sid.startswith("span_")

    def test_unique_across_calls(self):
        """Two calls should never return the same ID (uuid suffix guarantees this)."""
        ids = {make_span_id() for _ in range(100)}
        assert len(ids) == 100

    def test_roughly_sortable_by_time(self):
        """IDs generated later should sort after earlier ones (timestamp prefix)."""
        id_a = make_span_id()
        # Small delay to ensure different timestamp
        time.sleep(0.002)
        id_b = make_span_id()
        # Extract the timestamp portion (between first and second underscore)
        ts_a = int(id_a.split("_")[1])
        ts_b = int(id_b.split("_")[1])
        assert ts_b >= ts_a

    def test_format_has_three_parts(self):
        """Format should be span_{timestamp}_{hex8}."""
        sid = make_span_id()
        parts = sid.split("_")
        assert len(parts) == 3
        assert parts[0] == "span"
        # Timestamp should be numeric
        assert parts[1].isdigit()
        # Hex suffix should be 8 chars
        assert len(parts[2]) == 8


# =============================================================================
# TestTraceSpanCreation — TypedDict structure
# =============================================================================

class TestTraceSpanCreation:
    """Tests for creating TraceSpan and SeamSpan TypedDicts."""

    def test_trace_span_minimal(self):
        """TraceSpan with total=False allows creating with just a few fields."""
        span = TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="test")
        assert span["stage"] == "UNDERSTAND"
        assert span["swimlane"] == "deterministic"

    def test_trace_span_full(self, sample_span):
        """TraceSpan with all fields set should be a regular dict."""
        assert sample_span["decision"] == "metric_direction"
        assert sample_span["code_enforced"] is True
        assert sample_span["value"] == "down"

    def test_seam_span_creation(self):
        """SeamSpan (total=True) requires all fields."""
        seam = SeamSpan(
            trace_id="inv_test",
            stage="UNDERSTAND",
            schema="UnderstandResult",
            passed=True,
            tier="hard",
            checks={"rule_1": True},
            violations=[],
            timestamp_ms=1000,
        )
        assert seam["passed"] is True
        assert seam["violations"] == []


# =============================================================================
# TestInvestigationTrace — the core collector
# =============================================================================

class TestInvestigationTrace:
    """Tests for InvestigationTrace — emit, filtering, context, serialization."""

    def test_init_generates_trace_id(self):
        """Constructor should generate a trace_id starting with 'inv_'."""
        trace = InvestigationTrace(question="test")
        assert trace.trace_id.startswith("inv_")
        assert len(trace.trace_id) > 4

    def test_init_accepts_custom_trace_id(self):
        """Mode B orchestrator can supply its own trace_id for correlation."""
        trace = InvestigationTrace(question="test", trace_id="custom_123")
        assert trace.trace_id == "custom_123"

    def test_init_stores_question(self):
        """The original question is stored for downstream context."""
        trace = InvestigationTrace(question="CQ dropped 6.2%")
        assert trace.question == "CQ dropped 6.2%"

    def test_init_sets_created_at_ms(self):
        """created_at_ms should be a plausible millisecond timestamp."""
        before = int(time.time() * 1000)
        trace = InvestigationTrace(question="test")
        after = int(time.time() * 1000)
        assert before <= trace.created_at_ms <= after

    # -- emit() ---------------------------------------------------------------

    def test_emit_auto_fills_trace_id(self, trace):
        """emit() should inject the trace's trace_id if the span doesn't have one."""
        span = TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="test")
        trace.emit(span)
        assert span["trace_id"] == trace.trace_id

    def test_emit_auto_fills_span_id(self, trace):
        """emit() should generate a span_id if none provided."""
        span = TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="test")
        trace.emit(span)
        assert "span_id" in span
        assert span["span_id"].startswith("span_")

    def test_emit_auto_fills_timestamp_ms(self, trace):
        """emit() should set timestamp_ms to current time if not provided."""
        span = TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="test")
        before = int(time.time() * 1000)
        trace.emit(span)
        assert span["timestamp_ms"] >= before

    def test_emit_preserves_existing_trace_id(self, trace):
        """If span already has a trace_id, emit() should not overwrite it."""
        span = TraceSpan(
            trace_id="custom_span_trace",
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
        )
        trace.emit(span)
        assert span["trace_id"] == "custom_span_trace"

    def test_emit_preserves_existing_span_id(self, trace):
        """If span already has a span_id, emit() should not overwrite it."""
        span = TraceSpan(
            span_id="my_custom_id",
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
        )
        trace.emit(span)
        assert span["span_id"] == "my_custom_id"

    def test_emit_preserves_existing_timestamp(self, trace):
        """If span already has a timestamp_ms, emit() should not overwrite it."""
        span = TraceSpan(
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
            timestamp_ms=42,
        )
        trace.emit(span)
        assert span["timestamp_ms"] == 42

    def test_emit_appends_to_spans_list(self, trace):
        """Each emit() call should add one span to the internal list."""
        for i in range(3):
            trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool=f"tool_{i}"))
        assert len(trace._spans) == 3

    # -- emit_seam() ----------------------------------------------------------

    def test_emit_seam_records_event(self, trace):
        """emit_seam() should add a SeamSpan to the internal seam list."""
        trace.emit_seam(
            stage="UNDERSTAND",
            schema="UnderstandResult",
            passed=True,
            tier="hard",
            checks={"rule_1": True},
        )
        assert len(trace._seam_spans) == 1
        seam = trace._seam_spans[0]
        assert seam["stage"] == "UNDERSTAND"
        assert seam["passed"] is True
        assert seam["tier"] == "hard"

    def test_emit_seam_uses_trace_id(self, trace):
        """Seam span should carry the trace's trace_id."""
        trace.emit_seam(
            stage="HYPOTHESIZE",
            schema="HypothesisSet",
            passed=False,
            tier="soft",
            checks={"rule_min_three": False},
            violations=["Only 2 hypotheses"],
        )
        assert trace._seam_spans[0]["trace_id"] == trace.trace_id

    def test_emit_seam_defaults_violations_to_empty(self, trace):
        """If no violations kwarg, it should default to []."""
        trace.emit_seam(
            stage="UNDERSTAND",
            schema="UnderstandResult",
            passed=True,
            tier="hard",
            checks={},
        )
        assert trace._seam_spans[0]["violations"] == []

    def test_emit_seam_stores_violations(self, trace):
        """Violations list should be stored exactly as provided."""
        violations = ["Missing field A", "Missing field B"]
        trace.emit_seam(
            stage="DISPATCH",
            schema="FindingSet",
            passed=False,
            tier="soft",
            checks={"rule_1": False, "rule_2": False},
            violations=violations,
        )
        assert trace._seam_spans[0]["violations"] == violations

    # -- spans_for_stage() ----------------------------------------------------

    def test_spans_for_stage_filters_correctly(self, trace):
        """Should return only spans matching the requested stage."""
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="a"))
        trace.emit(TraceSpan(stage="HYPOTHESIZE", swimlane="llm_generated", tool="b"))
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="c"))

        understand_spans = trace.spans_for_stage("UNDERSTAND")
        assert len(understand_spans) == 2
        assert all(s["stage"] == "UNDERSTAND" for s in understand_spans)

    def test_spans_for_stage_empty_when_no_match(self, trace):
        """Should return empty list when no spans match the stage."""
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="a"))
        assert trace.spans_for_stage("DISPATCH") == []

    # -- seam_for_stage() -----------------------------------------------------

    def test_seam_for_stage_returns_most_recent(self, trace):
        """When multiple seams exist for a stage (retries), return the last one."""
        # First attempt fails
        trace.emit_seam(
            stage="SYNTHESIZE",
            schema="SynthesisReport",
            passed=False,
            tier="retry",
            checks={"rule_1": False},
            violations=["Missing tldr"],
        )
        # Retry succeeds
        trace.emit_seam(
            stage="SYNTHESIZE",
            schema="SynthesisReport",
            passed=True,
            tier="retry",
            checks={"rule_1": True},
        )
        seam = trace.seam_for_stage("SYNTHESIZE")
        assert seam is not None
        assert seam["passed"] is True

    def test_seam_for_stage_returns_none_when_missing(self, trace):
        """Should return None if no seam exists for the requested stage."""
        assert trace.seam_for_stage("UNDERSTAND") is None

    # -- agent_context_for() --------------------------------------------------

    def test_agent_context_includes_question(self, trace):
        """The context summary should include the original investigation question."""
        trace.emit(TraceSpan(
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
            decision="metric_direction",
            value="down",
        ))
        context = trace.agent_context_for("UNDERSTAND")
        assert "CQ dropped 6.2%" in context

    def test_agent_context_includes_decisions(self, trace):
        """Decision values should appear in the summary."""
        trace.emit(TraceSpan(
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
            decision="metric_direction",
            value="down",
            code_enforced=True,
        ))
        context = trace.agent_context_for("UNDERSTAND")
        assert "metric_direction" in context
        assert "down" in context
        assert "code-enforced" in context

    def test_agent_context_includes_llm_label(self, trace):
        """LLM-generated spans should be labeled differently from code-enforced."""
        trace.emit(TraceSpan(
            stage="HYPOTHESIZE",
            swimlane="llm_generated",
            tool="test",
            decision="hypothesis_inclusion",
            value="kept 3",
            code_enforced=False,
        ))
        context = trace.agent_context_for("HYPOTHESIZE")
        assert "llm-generated" in context

    def test_agent_context_includes_seam_status(self, trace):
        """Seam validation results should appear in context."""
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="test"))
        trace.emit_seam(
            stage="UNDERSTAND",
            schema="UnderstandResult",
            passed=True,
            tier="hard",
            checks={"rule_1": True},
        )
        context = trace.agent_context_for("UNDERSTAND")
        assert "PASSED" in context

    def test_agent_context_includes_seam_violations(self, trace):
        """Failed seam violations should appear as warnings."""
        trace.emit(TraceSpan(stage="HYPOTHESIZE", swimlane="llm_generated", tool="test"))
        trace.emit_seam(
            stage="HYPOTHESIZE",
            schema="HypothesisSet",
            passed=False,
            tier="soft",
            checks={"rule_min_three": False},
            violations=["Only 2 hypotheses"],
        )
        context = trace.agent_context_for("HYPOTHESIZE")
        assert "FAILED" in context
        assert "Only 2 hypotheses" in context

    def test_agent_context_no_data_message(self, trace):
        """When no spans or seams exist for a stage, return a no-data message."""
        context = trace.agent_context_for("DISPATCH")
        assert "No trace data" in context
        assert "DISPATCH" in context

    def test_agent_context_truncates_when_over_budget(self, trace):
        """Context should truncate to fit within the token budget."""
        # Emit many spans to create a long context
        for i in range(50):
            trace.emit(TraceSpan(
                stage="UNDERSTAND",
                swimlane="deterministic",
                tool=f"tool_{i}",
                decision=f"decision_{i}",
                value=f"value_{'x' * 100}_{i}",
                agent_context=f"Context detail {'y' * 200} for span {i}",
            ))
        # Use a very small budget to force truncation
        context = trace.agent_context_for("UNDERSTAND", max_tokens=50)
        # 50 tokens * 4 chars = 200 chars max
        assert len(context) <= 250  # 200 + some overhead for truncation message
        assert "truncated" in context

    def test_agent_context_includes_agent_context_field(self, trace):
        """When a span has agent_context, it should appear as 'Context:' in output."""
        trace.emit(TraceSpan(
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
            decision="metric_direction",
            value="down",
            agent_context="6.2% drop detected via step-change",
        ))
        context = trace.agent_context_for("UNDERSTAND")
        assert "Context:" in context
        assert "6.2% drop detected via step-change" in context

    # -- to_json() / from_json() roundtrip ------------------------------------

    def test_to_json_produces_valid_json(self, trace):
        """to_json() should produce parseable JSON."""
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="test"))
        result = json.loads(trace.to_json())
        assert "trace_id" in result
        assert "spans" in result

    def test_roundtrip_preserves_spans(self, trace):
        """from_json(to_json()) should preserve all spans."""
        trace.emit(TraceSpan(
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
            decision="metric_direction",
            value="down",
        ))
        trace.emit(TraceSpan(
            stage="HYPOTHESIZE",
            swimlane="llm_generated",
            tool="test2",
        ))

        restored = InvestigationTrace.from_json(trace.to_json())
        assert restored.trace_id == trace.trace_id
        assert restored.question == trace.question
        assert restored.created_at_ms == trace.created_at_ms
        assert len(restored._spans) == 2
        assert restored._spans[0]["decision"] == "metric_direction"

    def test_roundtrip_preserves_seam_spans(self, trace):
        """from_json(to_json()) should preserve seam validation records."""
        trace.emit_seam(
            stage="UNDERSTAND",
            schema="UnderstandResult",
            passed=True,
            tier="hard",
            checks={"rule_1": True},
        )
        restored = InvestigationTrace.from_json(trace.to_json())
        assert len(restored._seam_spans) == 1
        assert restored._seam_spans[0]["stage"] == "UNDERSTAND"
        assert restored._seam_spans[0]["passed"] is True

    def test_to_dict_summary_counts(self, trace):
        """to_dict() summary should include correct span and seam counts."""
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="a"))
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="b"))
        trace.emit_seam(
            stage="UNDERSTAND",
            schema="UnderstandResult",
            passed=True,
            tier="hard",
            checks={},
        )
        d = trace.to_dict()
        assert d["summary"]["total_spans"] == 2
        assert d["summary"]["total_seams"] == 1

    def test_to_dict_summary_tracks_ic9_decisions(self, trace):
        """Summary should list IC9 Invisible Decisions that were traced."""
        trace.emit(TraceSpan(
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
            decision="metric_direction",
            value="down",
        ))
        trace.emit(TraceSpan(
            stage="HYPOTHESIZE",
            swimlane="llm_generated",
            tool="test",
            decision="hypothesis_inclusion",
            value="kept 3",
        ))
        d = trace.to_dict()
        traced = d["summary"]["invisible_decisions_traced"]
        assert "metric_direction" in traced
        assert "hypothesis_inclusion" in traced

    def test_to_dict_summary_ignores_non_ic9_decisions(self, trace):
        """Non-IC9 decisions should NOT appear in invisible_decisions_traced."""
        trace.emit(TraceSpan(
            stage="UNDERSTAND",
            swimlane="deterministic",
            tool="test",
            decision="custom_decision",
            value="something",
        ))
        d = trace.to_dict()
        assert "custom_decision" not in d["summary"]["invisible_decisions_traced"]

    def test_to_dict_summary_stages_covered(self, trace):
        """Summary should list unique stages covered by spans."""
        trace.emit(TraceSpan(stage="UNDERSTAND", swimlane="deterministic", tool="a"))
        trace.emit(TraceSpan(stage="DISPATCH", swimlane="deterministic", tool="b"))
        d = trace.to_dict()
        stages = set(d["summary"]["stages_covered"])
        assert stages == {"UNDERSTAND", "DISPATCH"}


# =============================================================================
# TestValidateTraceCompleteness — schema.py
# =============================================================================

class TestValidateTraceCompleteness:
    """Tests for validate_trace_completeness() — checks IC9 coverage."""

    def test_complete_trace_passes(self, trace):
        """A trace with all 4 IC9 decisions and 4 seams should pass."""
        full_trace = _make_full_trace(trace)
        passed, issues = validate_trace_completeness(full_trace.to_dict())
        assert passed is True
        assert issues == []

    def test_missing_ic9_decision_fails(self, trace):
        """Missing an IC9 Invisible Decision should produce a specific issue."""
        # Emit 3 of 4 IC9 decisions (skip narrative_selection)
        for stage, decision, value in [
            ("UNDERSTAND", "metric_direction", "down"),
            ("HYPOTHESIZE", "hypothesis_inclusion", "kept 3"),
            ("DISPATCH", "context_construction", "full"),
        ]:
            trace.emit(TraceSpan(
                stage=stage, swimlane="deterministic", tool="test",
                decision=decision, value=value,
            ))
        for stage in REQUIRED_SEAMS:
            trace.emit_seam(stage=stage, schema="Test", passed=True, tier="hard", checks={})
        passed, issues = validate_trace_completeness(trace.to_dict())
        assert passed is False
        assert any("narrative_selection" in i for i in issues)

    def test_missing_seam_validation_fails(self, trace):
        """Missing a seam validation for a stage should produce a specific issue."""
        # Emit all IC9 decisions
        for stage, decision, value in [
            ("UNDERSTAND", "metric_direction", "down"),
            ("HYPOTHESIZE", "hypothesis_inclusion", "kept 3"),
            ("DISPATCH", "context_construction", "full"),
            ("SYNTHESIZE", "narrative_selection", "ranking regression"),
        ]:
            trace.emit(TraceSpan(
                stage=stage, swimlane="deterministic", tool="test",
                decision=decision, value=value,
            ))
        # Only emit 3 of 4 seams (skip DISPATCH)
        for stage in ["UNDERSTAND", "HYPOTHESIZE", "SYNTHESIZE"]:
            trace.emit_seam(stage=stage, schema="Test", passed=True, tier="hard", checks={})
        passed, issues = validate_trace_completeness(trace.to_dict())
        assert passed is False
        assert any("DISPATCH" in i and "seam" in i.lower() for i in issues)

    def test_missing_span_for_stage_fails(self, trace):
        """A stage with seam but no decision spans should fail."""
        # Only emit spans for 3 stages (skip SYNTHESIZE spans)
        for stage, decision, value in [
            ("UNDERSTAND", "metric_direction", "down"),
            ("HYPOTHESIZE", "hypothesis_inclusion", "kept 3"),
            ("DISPATCH", "context_construction", "full"),
        ]:
            trace.emit(TraceSpan(
                stage=stage, swimlane="deterministic", tool="test",
                decision=decision, value=value,
            ))
        for stage in REQUIRED_SEAMS:
            trace.emit_seam(stage=stage, schema="Test", passed=True, tier="hard", checks={})
        passed, issues = validate_trace_completeness(trace.to_dict())
        assert passed is False
        # Should flag both missing IC9 decision AND missing spans for SYNTHESIZE
        assert any("SYNTHESIZE" in i for i in issues)

    def test_empty_trace_reports_all_issues(self):
        """An empty trace dict should report issues for every missing element."""
        passed, issues = validate_trace_completeness({})
        assert passed is False
        # 4 IC9 decisions + 4 seams + 4 stage spans = 12 issues
        assert len(issues) == 12


# =============================================================================
# TestValidateSpanFields — schema.py
# =============================================================================

class TestValidateSpanFields:
    """Tests for validate_span_fields() — checks individual span correctness."""

    def test_valid_span_passes(self, sample_span):
        """A fully populated valid span should pass with no issues."""
        passed, issues = validate_span_fields(sample_span)
        assert passed is True
        assert issues == []

    def test_missing_required_field_fails(self):
        """Missing any of the 5 required fields should fail."""
        # Missing 'stage'
        span = {
            "trace_id": "inv_test",
            "swimlane": "deterministic",
            "tool": "test",
            "timestamp_ms": 1000,
        }
        passed, issues = validate_span_fields(span)
        assert passed is False
        assert any("stage" in i for i in issues)

    def test_none_required_field_fails(self):
        """A required field set to None should count as missing."""
        span = {
            "trace_id": "inv_test",
            "stage": None,
            "swimlane": "deterministic",
            "tool": "test",
            "timestamp_ms": 1000,
        }
        passed, issues = validate_span_fields(span)
        assert passed is False
        assert any("stage" in i for i in issues)

    def test_invalid_stage_value(self):
        """Stage must be one of the 4 valid values."""
        span = {
            "trace_id": "inv_test",
            "stage": "INVALID_STAGE",
            "swimlane": "deterministic",
            "tool": "test",
            "timestamp_ms": 1000,
        }
        passed, issues = validate_span_fields(span)
        assert passed is False
        assert any("Invalid stage" in i for i in issues)

    def test_invalid_swimlane_value(self):
        """Swimlane must be one of: deterministic, llm_generated, hybrid."""
        span = {
            "trace_id": "inv_test",
            "stage": "UNDERSTAND",
            "swimlane": "unknown_lane",
            "tool": "test",
            "timestamp_ms": 1000,
        }
        passed, issues = validate_span_fields(span)
        assert passed is False
        assert any("Invalid swimlane" in i for i in issues)

    def test_llm_span_with_alternatives_but_no_constrained_by(self):
        """LLM spans should use constrained_by, not alternatives_considered.

        IC9 finding: self-reported alternatives from LLMs are unreliable.
        The validator warns when an LLM span claims alternatives without
        specifying what rules constrained the output.
        """
        span = {
            "trace_id": "inv_test",
            "stage": "HYPOTHESIZE",
            "swimlane": "llm_generated",
            "tool": "test",
            "timestamp_ms": 1000,
            "alternatives_considered": [{"option": "A"}],
            # constrained_by is missing
        }
        passed, issues = validate_span_fields(span)
        assert passed is False
        assert any("constrained_by" in i for i in issues)

    def test_llm_span_with_both_alternatives_and_constrained_by_passes(self):
        """LLM span with both fields should pass (constrained_by is present)."""
        span = {
            "trace_id": "inv_test",
            "stage": "HYPOTHESIZE",
            "swimlane": "llm_generated",
            "tool": "test",
            "timestamp_ms": 1000,
            "alternatives_considered": [{"option": "A"}],
            "constrained_by": ["co_movement_consistency"],
        }
        passed, issues = validate_span_fields(span)
        assert passed is True

    def test_deterministic_span_with_alternatives_no_warning(self):
        """Deterministic spans can have alternatives_considered without constrained_by."""
        span = {
            "trace_id": "inv_test",
            "stage": "UNDERSTAND",
            "swimlane": "deterministic",
            "tool": "test",
            "timestamp_ms": 1000,
            "alternatives_considered": [{"option": "A"}],
        }
        passed, issues = validate_span_fields(span)
        assert passed is True

    def test_all_required_fields_missing(self):
        """Empty span should report all 5 missing required fields."""
        passed, issues = validate_span_fields({})
        assert passed is False
        assert len(issues) == 5  # trace_id, stage, swimlane, tool, timestamp_ms

    def test_valid_stages_are_accepted(self):
        """All 4 valid stage values should pass validation."""
        for stage in ["UNDERSTAND", "HYPOTHESIZE", "DISPATCH", "SYNTHESIZE"]:
            span = {
                "trace_id": "inv_test",
                "stage": stage,
                "swimlane": "deterministic",
                "tool": "test",
                "timestamp_ms": 1000,
            }
            passed, _ = validate_span_fields(span)
            assert passed is True, f"Stage '{stage}' should be valid"

    def test_valid_swimlanes_are_accepted(self):
        """All 3 valid swimlane values should pass validation."""
        for swimlane in ["deterministic", "llm_generated", "hybrid"]:
            span = {
                "trace_id": "inv_test",
                "stage": "UNDERSTAND",
                "swimlane": swimlane,
                "tool": "test",
                "timestamp_ms": 1000,
            }
            passed, _ = validate_span_fields(span)
            assert passed is True, f"Swimlane '{swimlane}' should be valid"


# =============================================================================
# TestEmitDeterministicSpan — trace/helpers.py
# =============================================================================

class TestEmitDeterministicSpan:
    """Tests for the convenience helper that emits deterministic spans."""

    def test_emits_span_when_trace_provided(self):
        from trace.helpers import emit_deterministic_span
        from trace.collector import InvestigationTrace

        trace = InvestigationTrace(question="test")
        emit_deterministic_span(
            trace,
            tool="core.anomaly.check_data_quality",
            decision="data_quality_status",
            value="pass",
            human_summary="Data quality: pass",
            agent_context="data_quality=pass, completeness=99.1",
        )
        spans = trace.spans_for_stage("UNDERSTAND")
        assert len(spans) == 1
        assert spans[0]["decision"] == "data_quality_status"
        assert spans[0]["swimlane"] == "deterministic"
        assert spans[0]["code_enforced"] is True

    def test_noop_when_trace_is_none(self):
        from trace.helpers import emit_deterministic_span

        # Should not raise — silently no-ops
        emit_deterministic_span(
            None,
            tool="core.anomaly.check_data_quality",
            decision="data_quality_status",
            value="pass",
            human_summary="Data quality: pass",
            agent_context="data_quality=pass",
        )

    def test_custom_stage(self):
        from trace.helpers import emit_deterministic_span
        from trace.collector import InvestigationTrace

        trace = InvestigationTrace(question="test")
        emit_deterministic_span(
            trace,
            tool="core.diagnose.archetype_recognition",
            decision="archetype",
            value="mix_shift",
            human_summary="Archetype: mix_shift",
            agent_context="archetype=mix_shift",
            stage="HYPOTHESIZE",
        )
        spans = trace.spans_for_stage("HYPOTHESIZE")
        assert len(spans) == 1
        assert spans[0]["stage"] == "HYPOTHESIZE"

    def test_includes_inputs_outputs_when_provided(self):
        from trace.helpers import emit_deterministic_span
        from trace.collector import InvestigationTrace

        trace = InvestigationTrace(question="test")
        emit_deterministic_span(
            trace,
            tool="core.decompose.compute_aggregate_delta",
            decision="metric_direction",
            value="down",
            human_summary="CQ down 6.2%",
            agent_context="direction=down, delta=-6.2",
            inputs={"metric": "click_quality_value", "row_count": 500},
            outputs={"direction": "down", "delta_pct": -6.2},
        )
        span = trace.spans_for_stage("UNDERSTAND")[0]
        assert span["inputs"]["metric"] == "click_quality_value"
        assert span["outputs"]["delta_pct"] == -6.2
