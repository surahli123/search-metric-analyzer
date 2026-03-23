"""Tests for harness/phoenix_tracer.py — Phoenix/OTel observability layer.

TDD: Tests written first, implementation follows.
Organized by implementation step (1-4, 8).
"""

import logging
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ---------------------------------------------------------------------------
# Step 1: Scaffold — import guard, register_phoenix(), idempotency
# ---------------------------------------------------------------------------


class TestPhoenixAvailableFlag:
    """PHOENIX_AVAILABLE flag must reflect whether OTel deps are installed."""

    def test_phoenix_available_flag_false_without_deps(self):
        """When OTel packages are missing, PHOENIX_AVAILABLE should be False.

        WHY: The entire Phoenix integration is optional. If a user hasn't
        installed dev dependencies, the tracer module must still import
        without errors — it just does nothing.
        """
        # Mock the import to raise ImportError, simulating missing packages
        import importlib
        import harness.phoenix_tracer as pt

        with patch.dict("sys.modules", {
            "opentelemetry": None,
            "opentelemetry.sdk": None,
            "opentelemetry.sdk.trace": None,
            "opentelemetry.sdk.trace.export": None,
            "opentelemetry.trace": None,
            "openinference.instrumentation.anthropic": None,
        }):
            # Force reimport to trigger the try/except
            importlib.reload(pt)
            assert pt.PHOENIX_AVAILABLE is False

        # Restore the module to its real state for other tests
        importlib.reload(pt)

    def test_phoenix_available_flag_true_with_deps(self):
        """When OTel packages are installed, PHOENIX_AVAILABLE should be True.

        WHY: When deps ARE present, we want the full observability pipeline
        active. This confirms the happy path import guard works.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        # This test runs with deps installed, so it should be True
        # If deps aren't installed in test env, skip
        try:
            import opentelemetry  # noqa: F401
            assert PHOENIX_AVAILABLE is True
        except ImportError:
            pytest.skip("OTel deps not installed — can't test True path")


class TestRegisterPhoenix:
    """register_phoenix() sets up OTel tracer provider + Anthropic instrumentor."""

    def test_register_phoenix_returns_provider(self):
        """register_phoenix() should return a TracerProvider when deps available.

        WHY: The caller needs the provider to later call flush().
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.phoenix_tracer import register_phoenix

        # Use a no-op endpoint so we don't need a running Phoenix server
        provider = register_phoenix(
            endpoint="http://localhost:0",  # Will fail to connect — that's fine
            project_name="test-project",
        )
        assert provider is not None

    def test_register_phoenix_noop_when_unavailable(self):
        """register_phoenix() returns None when PHOENIX_AVAILABLE is False.

        WHY: Graceful degradation — callers check for None and skip OTel work.
        """
        from harness import phoenix_tracer as pt

        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            result = pt.register_phoenix()
            assert result is None

    def test_register_phoenix_idempotent(self):
        """Calling register_phoenix() twice returns the same provider (R1).

        WHY: The orchestrator calls register_phoenix() at the start of every
        pipeline run. Without idempotency, we'd create duplicate providers
        and AnthropicInstrumentor would monkey-patch the SDK multiple times.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness import phoenix_tracer as pt

        # Reset module state so we start clean
        pt._tracer_provider = None

        provider1 = pt.register_phoenix(
            endpoint="http://localhost:0",
            project_name="test-idempotent",
        )
        provider2 = pt.register_phoenix(
            endpoint="http://localhost:0",
            project_name="test-idempotent",
        )
        assert provider1 is provider2

        # Clean up
        pt._tracer_provider = None

    def test_register_phoenix_calls_anthropic_instrumentor(self):
        """register_phoenix() must call AnthropicInstrumentor().instrument() (R4).

        WHY: Auto-instrumentation of Anthropic SDK calls requires explicit
        invocation — it doesn't happen automatically just from importing.
        Without this call, LLM spans won't appear in traces.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness import phoenix_tracer as pt

        # Reset module state
        pt._tracer_provider = None

        with patch(
            "harness.phoenix_tracer.AnthropicInstrumentor"
        ) as MockInstrumentor:
            mock_instance = MagicMock()
            MockInstrumentor.return_value = mock_instance

            pt.register_phoenix(
                endpoint="http://localhost:0",
                project_name="test-instrumentor",
            )

            # Verify AnthropicInstrumentor was instantiated and instrument() called
            MockInstrumentor.assert_called_once()
            mock_instance.instrument.assert_called_once()

        # Clean up
        pt._tracer_provider = None

    def test_register_phoenix_calls_openai_instrumentor(self):
        """register_phoenix() must call OpenAIInstrumentor().instrument().

        WHY: Without this, OpenAI-compatible API calls (Novita, Groq, etc.)
        are invisible in Phoenix traces. Same pattern as Anthropic instrumentor.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness import phoenix_tracer as pt

        # Reset module state
        pt._tracer_provider = None

        # Patch at the source module — OpenAIInstrumentor is imported locally
        # inside register_phoenix(), so we patch where it lives, not where
        # it's consumed.
        with patch(
            "harness.phoenix_tracer.AnthropicInstrumentor"
        ), patch(
            "openinference.instrumentation.openai.OpenAIInstrumentor"
        ) as MockOpenAIInstrumentor:
            mock_instance = MagicMock()
            MockOpenAIInstrumentor.return_value = mock_instance

            pt.register_phoenix(
                endpoint="http://localhost:0",
                project_name="test-openai-instrumentor",
            )

            MockOpenAIInstrumentor.assert_called_once()
            mock_instance.instrument.assert_called_once()

        # Clean up
        pt._tracer_provider = None

    def test_instrumentor_exception_graceful_skip(self):
        """If an instrumentor raises a non-ImportError, pipeline should continue.

        WHY: Observability must never block the investigation pipeline.
        A version mismatch or API change in an instrumentor should degrade
        gracefully — log a warning and continue without tracing.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness import phoenix_tracer as pt

        # Reset module state
        pt._tracer_provider = None

        # Make AnthropicInstrumentor raise a RuntimeError (simulating version mismatch)
        with patch(
            "harness.phoenix_tracer.AnthropicInstrumentor"
        ) as MockAnthropicInstrumentor:
            mock_instance = MagicMock()
            mock_instance.instrument.side_effect = RuntimeError("version mismatch")
            MockAnthropicInstrumentor.return_value = mock_instance

            # Should NOT raise — should log warning and continue
            provider = pt.register_phoenix(
                endpoint="http://localhost:0",
                project_name="test-graceful-skip",
            )

            # Pipeline should still get a valid provider
            assert provider is not None

        # Clean up
        pt._tracer_provider = None


# ---------------------------------------------------------------------------
# Step 2: stage_span() — CHAIN span context manager
# ---------------------------------------------------------------------------


class TestStageSpan:
    """stage_span() wraps a pipeline stage in an OTel CHAIN span."""

    def _setup_in_memory_provider(self):
        """Create a TracerProvider with InMemorySpanExporter for testing.

        Returns (provider, exporter) tuple so tests can inspect captured spans.

        WHY reset global state: OTel's set_tracer_provider() refuses to
        override an already-set provider. Earlier tests (register_phoenix)
        may have set it. We reset the global _TRACER_PROVIDER to allow
        test isolation.
        """
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry import trace as otel_trace

        # Reset OTel global state so set_tracer_provider() works
        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        # Also reset our module's cached provider
        import harness.phoenix_tracer as pt
        pt._tracer_provider = None

        return provider, exporter

    def test_stage_span_creates_chain_span(self):
        """stage_span() should create an OTel span for the pipeline stage.

        WHY: Each pipeline stage (UNDERSTAND, HYPOTHESIZE, etc.) needs its
        own span so LLM calls nest inside it in the Phoenix trace tree.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.phoenix_tracer import stage_span

        provider, exporter = self._setup_in_memory_provider()

        with stage_span("UNDERSTAND", mode="medium"):
            pass  # Stage work would happen here

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "UNDERSTAND"

    def test_stage_span_sets_stage_attribute(self):
        """stage_span() should set 'stage' and 'mode' as span attributes.

        WHY: These attributes let you filter/group traces by stage and mode
        in the Phoenix UI — essential for comparing performance across modes.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.phoenix_tracer import stage_span

        provider, exporter = self._setup_in_memory_provider()

        with stage_span("HYPOTHESIZE", mode="complex"):
            pass

        spans = exporter.get_finished_spans()
        attrs = dict(spans[0].attributes)
        assert attrs["sma.stage"] == "HYPOTHESIZE"
        assert attrs["sma.mode"] == "complex"

    def test_stage_span_noop_when_unavailable(self):
        """stage_span() should yield a no-op context when Phoenix is unavailable.

        WHY: The orchestrator wraps stages unconditionally — the no-op
        pattern means no if-guards needed at the call site.
        """
        from harness import phoenix_tracer as pt

        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            # Should not crash, should yield None
            with pt.stage_span("UNDERSTAND", mode="medium") as span:
                assert span is None

    def test_stage_span_logs_warning_on_internal_error(self, caplog):
        """stage_span() should log a warning if OTel itself errors.

        WHY: Critical gap #1 from eng review — OTel errors must never
        crash the pipeline. They're observability, not business logic.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness import phoenix_tracer as pt

        # Force an OTel error by patching the tracer to raise
        with patch.object(
            pt, "PHOENIX_AVAILABLE", True
        ), patch(
            "harness.phoenix_tracer.otel_trace"
        ) as mock_otel:
            mock_otel.get_tracer.side_effect = RuntimeError("OTel broke")

            with caplog.at_level(logging.WARNING):
                with pt.stage_span("UNDERSTAND", mode="medium") as span:
                    # Should still yield (None), not crash
                    assert span is None

            assert "stage_span" in caplog.text or "OTel" in caplog.text


# ---------------------------------------------------------------------------
# Step 3: dual_emit() — synchronized emission to trace + OTel
# ---------------------------------------------------------------------------


class TestDualEmit:
    """dual_emit() writes to InvestigationTrace AND OTel in one call."""

    def _setup_in_memory_provider(self):
        """Shared test helper — see TestStageSpan for docstring."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry import trace as otel_trace

        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        import harness.phoenix_tracer as pt
        pt._tracer_provider = None

        return provider, exporter

    def _make_trace(self):
        """Create a minimal InvestigationTrace for testing."""
        from trace.collector import InvestigationTrace
        return InvestigationTrace(question="test question")

    def test_dual_emit_writes_to_investigation_trace(self):
        """dual_emit() must write a TraceSpan to InvestigationTrace.

        WHY: The existing enforcement trace must continue to work exactly
        as before — dual_emit is additive, not replacing.
        """
        from harness.phoenix_tracer import dual_emit

        trace = self._make_trace()

        dual_emit(
            trace=trace,
            tool="test.tool",
            decision="test_decision",
            value="test_value",
            human_summary="Test summary",
            agent_context="test context",
            stage="UNDERSTAND",
        )

        spans = trace.to_dict()["spans"]
        assert len(spans) == 1
        assert spans[0]["tool"] == "test.tool"
        assert spans[0]["decision"] == "test_decision"
        assert spans[0]["value"] == "test_value"
        assert spans[0]["swimlane"] == "deterministic"
        assert spans[0]["code_enforced"] is True

    def test_dual_emit_writes_otel_attributes(self):
        """dual_emit() must write decision info as OTel span attributes.

        WHY: This is the bridge — domain decisions visible in Phoenix UI
        as span attributes, not just in the enforcement trace JSON.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.phoenix_tracer import dual_emit, stage_span

        provider, exporter = self._setup_in_memory_provider()
        trace = self._make_trace()

        # dual_emit needs a current OTel span to attach attributes to
        with stage_span("UNDERSTAND", mode="medium"):
            dual_emit(
                trace=trace,
                tool="test.tool",
                decision="test_decision",
                value="test_value",
                human_summary="Test summary",
                agent_context="test context",
                stage="UNDERSTAND",
            )

        spans = exporter.get_finished_spans()
        # The stage span should have our attributes
        stage_attrs = dict(spans[0].attributes)
        assert stage_attrs.get("sma.decision") == "test_decision"
        assert stage_attrs.get("sma.decision.value") == "test_value"

    def test_dual_emit_noop_otel_when_unavailable(self):
        """dual_emit() skips OTel writes when Phoenix is unavailable.

        WHY: InvestigationTrace still gets the span, but OTel part is skipped.
        No crash, no error, just the enforcement side working as usual.
        """
        from harness import phoenix_tracer as pt

        trace = self._make_trace()

        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            pt.dual_emit(
                trace=trace,
                tool="test.tool",
                decision="test_decision",
                value="test_value",
                human_summary="Test summary",
                agent_context="test context",
            )

        # InvestigationTrace should still have the span
        spans = trace.to_dict()["spans"]
        assert len(spans) == 1

    def test_dual_emit_noop_when_trace_is_none(self):
        """dual_emit() does nothing when trace is None.

        WHY: Follows the same no-op pattern as emit_deterministic_span() —
        callers don't need if-guards around every emission.
        """
        from harness.phoenix_tracer import dual_emit

        # Should not crash
        dual_emit(
            trace=None,
            tool="test.tool",
            decision="test_decision",
            value="test_value",
            human_summary="Test summary",
            agent_context="test context",
        )

    def test_dual_emit_deterministic_swimlane(self):
        """Default swimlane="deterministic" sets code_enforced=True (R2).

        WHY: UNDERSTAND stage emits are deterministic (Python code, not LLM).
        They must be recorded as code_enforced=True so the trace audit
        knows which decisions were mechanically enforced vs LLM-generated.
        """
        from harness.phoenix_tracer import dual_emit

        trace = self._make_trace()

        dual_emit(
            trace=trace,
            tool="test.tool",
            decision="test_decision",
            value="test_value",
            human_summary="Test summary",
            agent_context="test context",
            swimlane="deterministic",
        )

        span = trace.to_dict()["spans"][0]
        assert span["swimlane"] == "deterministic"
        assert span["code_enforced"] is True

    def test_dual_emit_llm_swimlane(self):
        """swimlane="llm_generated" sets code_enforced=False (R2).

        WHY: HYPOTHESIZE/DISPATCH/SYNTHESIZE stages use LLM output.
        These decisions are NOT code-enforced — the LLM chose the content.
        Without the swimlane param, 3/4 stages would incorrectly appear
        as deterministic in the trace.
        """
        from harness.phoenix_tracer import dual_emit

        trace = self._make_trace()

        dual_emit(
            trace=trace,
            tool="test.tool",
            decision="test_decision",
            value="test_value",
            human_summary="Test summary",
            agent_context="test context",
            swimlane="llm_generated",
        )

        span = trace.to_dict()["spans"][0]
        assert span["swimlane"] == "llm_generated"
        assert span["code_enforced"] is False


# ---------------------------------------------------------------------------
# Step 4: emit_guardrail() + flush()
# ---------------------------------------------------------------------------


class TestEmitGuardrail:
    """emit_guardrail() creates GUARDRAIL spans for seam validations."""

    def _setup_in_memory_provider(self):
        """Shared test helper."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry import trace as otel_trace

        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        import harness.phoenix_tracer as pt
        pt._tracer_provider = None

        return provider, exporter

    def test_emit_guardrail_creates_guardrail_span(self):
        """emit_guardrail() should create an OTel span for the seam validation.

        WHY: Seam validations are business rule gates — seeing them in the
        Phoenix trace tree tells you which gates passed/failed and why.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.phoenix_tracer import emit_guardrail, stage_span

        provider, exporter = self._setup_in_memory_provider()

        with stage_span("UNDERSTAND", mode="medium"):
            emit_guardrail(
                stage="UNDERSTAND",
                passed=True,
                tier="hard",
                violations=[],
            )

        spans = exporter.get_finished_spans()
        # Should have 2 spans: the guardrail + the parent stage
        guardrail_spans = [s for s in spans if "guardrail" in s.name.lower()]
        assert len(guardrail_spans) == 1

    def test_emit_guardrail_sets_tier_and_violations(self):
        """emit_guardrail() sets tier, passed, and violations as attributes.

        WHY: These attributes let you filter traces by gate tier (hard/soft/retry)
        and quickly find investigations that hit validation failures.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.phoenix_tracer import emit_guardrail, stage_span

        provider, exporter = self._setup_in_memory_provider()

        with stage_span("HYPOTHESIZE", mode="medium"):
            emit_guardrail(
                stage="HYPOTHESIZE",
                passed=False,
                tier="soft",
                violations=["missing_hypothesis_id", "no_evidence"],
            )

        spans = exporter.get_finished_spans()
        guardrail_spans = [s for s in spans if "guardrail" in s.name.lower()]
        attrs = dict(guardrail_spans[0].attributes)
        assert attrs["sma.guardrail.stage"] == "HYPOTHESIZE"
        assert attrs["sma.guardrail.passed"] is False
        assert attrs["sma.guardrail.tier"] == "soft"
        assert "missing_hypothesis_id" in attrs["sma.guardrail.violations"]


class TestFlush:
    """flush() force-flushes the OTel batch exporter."""

    def test_flush_calls_force_flush(self):
        """flush() should call force_flush() on the tracer provider.

        WHY: Batch exporter buffers spans. Without explicit flush at pipeline
        end, short investigations might exit before spans are sent to Phoenix.
        """
        from harness.phoenix_tracer import flush

        mock_provider = MagicMock()
        mock_provider.force_flush.return_value = True

        flush(mock_provider, timeout_ms=5000)

        mock_provider.force_flush.assert_called_once_with(timeout_millis=5000)

    def test_flush_logs_warning_on_timeout(self, caplog):
        """flush() should log a warning if force_flush times out.

        WHY: Critical gap #2 from eng review — a blocked flush must never
        prevent the CLI from exiting. Log the timeout and move on.
        """
        from harness.phoenix_tracer import flush

        mock_provider = MagicMock()
        mock_provider.force_flush.return_value = False  # Timeout

        with caplog.at_level(logging.WARNING):
            flush(mock_provider, timeout_ms=100)

        assert "flush" in caplog.text.lower() or "timeout" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Step 5a: Orchestrator structural wrapping (stage spans + flush)
# ---------------------------------------------------------------------------


class TestOrchestratorPhoenixIntegration:
    """Test Phoenix stage spans wrap orchestrator pipeline stages."""

    def _setup_in_memory_provider(self):
        """Shared test helper."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry import trace as otel_trace

        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        import harness.phoenix_tracer as pt
        pt._tracer_provider = None

        return provider, exporter

    def _make_mock_llm(self):
        """Create a mock LLM that returns valid JSON for each stage."""
        import json

        def mock_llm(prompt, system=None, max_tokens=4096):
            # Return valid JSON that passes seam validation
            if "hypothes" in prompt.lower() or "hypothes" in (system or "").lower():
                return json.dumps({
                    "hypotheses": [
                        {
                            "hypothesis_id": "H1",
                            "hypothesis": "Ranking regression",
                            "priority": 1,
                            "evidence_needed": ["ranking model version"],
                            "expected_impact": "high",
                        }
                    ],
                    "reasoning": "Test reasoning",
                })
            elif "dispatch" in prompt.lower() or "investigat" in prompt.lower():
                return json.dumps({
                    "finding": "Evidence supports ranking regression",
                    "evidence": ["ranking model v2 deployed"],
                    "confidence": 0.8,
                    "verdict": "supported",
                })
            elif "synthe" in prompt.lower() or "synthe" in (system or "").lower():
                return json.dumps({
                    "summary": "Click Quality dropped due to ranking regression",
                    "root_cause": "Ranking model v2 deployed",
                    "confidence": "high",
                    "severity": "P1",
                    "recommended_actions": ["Rollback ranking model"],
                    "evidence_summary": "Model v2 caused 6% drop",
                })
            return "{}"

        return mock_llm

    def _make_test_rows(self):
        """Create minimal metric rows for pipeline execution."""
        return [
            {
                "period": "current",
                "click_quality_value": 0.25,
                "ai_trigger": 0.4,
                "ai_success": 0.6,
            },
            {
                "period": "baseline",
                "click_quality_value": 0.31,
                "ai_trigger": 0.4,
                "ai_success": 0.6,
            },
        ]

    def test_pipeline_creates_stage_spans(self):
        """Running the pipeline should create OTel spans for each stage.

        WHY: This is the core value prop — each stage appears as a CHAIN
        span in Phoenix, with LLM calls nested inside.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        provider, exporter = self._setup_in_memory_provider()

        from harness.orchestrator import SearchMetricOrchestrator

        orch = SearchMetricOrchestrator(llm_callable=self._make_mock_llm())
        result = orch.run(
            question="Click Quality dropped 6.2% WoW",
            rows=self._make_test_rows(),
            metric_field="click_quality_value",
            dimensions=["period"],
        )

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        # Should have stage spans (at minimum UNDERSTAND)
        # The exact set depends on whether the pipeline completes
        assert any("UNDERSTAND" in name for name in span_names), (
            f"Expected UNDERSTAND span, got: {span_names}"
        )

    def test_pipeline_works_without_phoenix(self):
        """Pipeline should work normally when Phoenix is disabled.

        WHY: Graceful degradation — the existing test suite must pass
        unchanged when Phoenix deps aren't installed or are disabled.
        """
        from harness import phoenix_tracer as pt

        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            from harness.orchestrator import SearchMetricOrchestrator

            orch = SearchMetricOrchestrator(
                llm_callable=self._make_mock_llm()
            )
            result = orch.run(
                question="Click Quality dropped 6.2% WoW",
                rows=self._make_test_rows(),
                metric_field="click_quality_value",
                dimensions=["period"],
            )

            # Pipeline should still produce a valid result
            assert result["status"] in ("complete", "blocked")
            assert "trace" in result

    def test_pipeline_flushes_at_end(self):
        """Pipeline should call flush() before returning.

        WHY: Without flush, batch-exported spans might never reach Phoenix
        for short-lived investigations.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness import phoenix_tracer as pt

        provider, exporter = self._setup_in_memory_provider()

        # Patch flush at the orchestrator level (it imports at module load)
        with patch("harness.orchestrator.flush", wraps=pt.flush) as mock_flush:
            from harness.orchestrator import SearchMetricOrchestrator

            orch = SearchMetricOrchestrator(
                llm_callable=self._make_mock_llm()
            )
            result = orch.run(
                question="Click Quality dropped 6.2% WoW",
                rows=self._make_test_rows(),
                metric_field="click_quality_value",
                dimensions=["period"],
            )

            # flush() should have been called
            assert mock_flush.called

    def test_investigation_trace_output_unchanged_after_migration(self):
        """InvestigationTrace output must be identical after dual_emit migration.

        WHY: The enforcement trace is the source of truth for eval scoring
        and stress tests. If dual_emit changes the trace output shape,
        the eval pipeline breaks silently.
        """
        from harness.orchestrator import SearchMetricOrchestrator
        from harness import phoenix_tracer as pt

        # Run with Phoenix disabled to get pure InvestigationTrace output
        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            orch = SearchMetricOrchestrator(
                llm_callable=self._make_mock_llm()
            )
            result = orch.run(
                question="Click Quality dropped 6.2% WoW",
                rows=self._make_test_rows(),
                metric_field="click_quality_value",
                dimensions=["period"],
            )

        trace_data = result.get("trace", {})

        # The trace should have spans (from UNDERSTAND at minimum)
        # and the spans should have the expected fields
        if trace_data.get("spans"):
            span = trace_data["spans"][0]
            # Core fields must be present
            assert "stage" in span
            assert "swimlane" in span
            assert "tool" in span
            assert "decision" in span
            assert "code_enforced" in span


# ---------------------------------------------------------------------------
# Step 6: seam_validator — GUARDRAIL span emission
# ---------------------------------------------------------------------------


class TestSeamValidatorGuardrail:
    """validate_seam() emits GUARDRAIL spans to Phoenix."""

    def _setup_in_memory_provider(self):
        """Shared test helper."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry import trace as otel_trace

        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        import harness.phoenix_tracer as pt
        pt._tracer_provider = None

        return provider, exporter

    def test_validate_seam_emits_guardrail_span(self):
        """validate_seam() should emit a GUARDRAIL span when Phoenix is available.

        WHY: Seam validations are business rule gates. Seeing them in the
        Phoenix trace tree makes it easy to find which validations failed.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from contracts.seam_validator import validate_seam
        from trace.collector import InvestigationTrace

        provider, exporter = self._setup_in_memory_provider()
        trace = InvestigationTrace(question="test")

        # Create a minimal valid UNDERSTAND result
        result = {
            "question": "test",
            "metric": "click_quality_value",
            "data_quality_status": "pass",
            "metric_direction": "down",
            "severity": "P1",
            "direction": "down",
            "step_change": None,
            "co_movement_pattern": {"likely_cause": "test"},
            "mix_shift_result": None,
            "data_quality_details": {"status": "pass"},
            "decomposition": {},
            "diagnosis": {},
        }

        validate_seam(result=result, stage="UNDERSTAND", trace=trace)

        spans = exporter.get_finished_spans()
        guardrail_names = [s.name for s in spans if "guardrail" in s.name.lower()]
        assert len(guardrail_names) >= 1, (
            f"Expected guardrail span, got: {[s.name for s in spans]}"
        )

    def test_validate_seam_guardrail_noop_without_phoenix(self):
        """validate_seam() should work normally without Phoenix.

        WHY: Graceful degradation — existing behavior unchanged.
        """
        from contracts.seam_validator import validate_seam
        from trace.collector import InvestigationTrace
        from harness import phoenix_tracer as pt

        trace = InvestigationTrace(question="test")

        result = {
            "question": "test",
            "metric": "click_quality_value",
            "data_quality_status": "pass",
            "metric_direction": "down",
            "severity": "P1",
            "direction": "down",
            "step_change": None,
            "co_movement_pattern": {"likely_cause": "test"},
            "mix_shift_result": None,
            "data_quality_details": {"status": "pass"},
            "decomposition": {},
            "diagnosis": {},
        }

        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            # Should not crash
            validation = validate_seam(
                result=result, stage="UNDERSTAND", trace=trace
            )
            assert validation["passed"] is True


# ---------------------------------------------------------------------------
# Step 7: DAGExecutor — OTel context propagation in workers
# ---------------------------------------------------------------------------


class TestDAGExecutorPhoenix:
    """DAGExecutor propagates OTel context to ThreadPoolExecutor workers."""

    def _setup_in_memory_provider(self):
        """Shared test helper."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry import trace as otel_trace

        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        import harness.phoenix_tracer as pt
        pt._tracer_provider = None

        return provider, exporter

    def test_dag_executor_works_without_phoenix(self):
        """DAGExecutor should work normally without Phoenix.

        WHY: Graceful degradation — parallel dispatch is critical
        pipeline infrastructure. It must never break because of OTel.
        """
        from harness.dag_executor import DAGExecutor
        from harness import phoenix_tracer as pt
        from trace.collector import InvestigationTrace

        trace = InvestigationTrace(question="test")

        def mock_investigate(hyp, context):
            return {
                "agent_name": "test",
                "hypothesis_id": hyp["hypothesis_id"],
                "verdict": "supported",
                "confidence": 0.8,
                "evidence": ["test evidence"],
                "narrative": "Test finding",
                "adjacent_observations": [],
            }

        executor = DAGExecutor(investigate_fn=mock_investigate)

        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            result = executor.execute(
                hypotheses=[
                    {"hypothesis_id": "H1", "hypothesis": "test"},
                ],
                context={"understand_result": {}},
                trace=trace,
            )

        assert len(result["findings"]) == 1
        assert result["findings"][0]["verdict"] == "supported"

    def test_dag_executor_propagates_otel_context(self):
        """Worker threads should inherit the parent OTel context.

        WHY: Without explicit context propagation, ThreadPoolExecutor
        workers create orphan spans — they don't nest inside the
        DISPATCH stage span in the Phoenix trace tree.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.dag_executor import DAGExecutor
        from harness.phoenix_tracer import stage_span
        from trace.collector import InvestigationTrace
        from opentelemetry import trace as otel_trace

        provider, exporter = self._setup_in_memory_provider()
        trace = InvestigationTrace(question="test")

        # Track whether workers see a parent context
        worker_had_context = []

        def mock_investigate(hyp, context):
            # Check if OTel context is active in this worker thread
            current = otel_trace.get_current_span()
            worker_had_context.append(current.is_recording())
            return {
                "agent_name": "test",
                "hypothesis_id": hyp["hypothesis_id"],
                "verdict": "supported",
                "confidence": 0.8,
                "evidence": ["test evidence"],
                "narrative": "Test finding",
                "adjacent_observations": [],
            }

        executor = DAGExecutor(investigate_fn=mock_investigate)

        # Execute within a stage span to provide parent context
        with stage_span("DISPATCH", mode="complex"):
            result = executor.execute(
                hypotheses=[
                    {"hypothesis_id": "H1", "hypothesis": "test"},
                ],
                context={"understand_result": {}},
                trace=trace,
            )

        # Workers should have seen an active OTel context
        assert len(worker_had_context) == 1
        assert worker_had_context[0] is True, (
            "Worker thread did not have an active OTel context — "
            "context propagation is not working"
        )


# ---------------------------------------------------------------------------
# Step 8: Full integration test + graceful degradation
# ---------------------------------------------------------------------------


class TestFullIntegration:
    """End-to-end tests for the complete Phoenix integration."""

    def _setup_in_memory_provider(self):
        """Shared test helper."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
            InMemorySpanExporter,
        )
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry import trace as otel_trace

        otel_trace._TRACER_PROVIDER = None
        otel_trace._TRACER_PROVIDER_SET_ONCE._done = False

        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        otel_trace.set_tracer_provider(provider)

        import harness.phoenix_tracer as pt
        pt._tracer_provider = None

        return provider, exporter

    def _make_mock_llm(self):
        """Create a mock LLM returning valid JSON for each stage."""
        import json

        def mock_llm(prompt, system=None, max_tokens=4096):
            if "hypothes" in prompt.lower() or "hypothes" in (system or "").lower():
                return json.dumps({
                    "hypotheses": [
                        {
                            "hypothesis_id": "H1",
                            "hypothesis": "Ranking regression",
                            "priority": 1,
                            "evidence_needed": ["ranking model version"],
                            "expected_impact": "high",
                        }
                    ],
                    "reasoning": "Test reasoning",
                })
            elif "dispatch" in prompt.lower() or "investigat" in prompt.lower():
                return json.dumps({
                    "finding": "Evidence supports ranking regression",
                    "evidence": ["ranking model v2 deployed"],
                    "confidence": 0.8,
                    "verdict": "supported",
                })
            elif "synthe" in prompt.lower() or "synthe" in (system or "").lower():
                return json.dumps({
                    "summary": "Click Quality dropped due to ranking regression",
                    "root_cause": "Ranking model v2 deployed",
                    "confidence": "high",
                    "severity": "P1",
                    "recommended_actions": ["Rollback ranking model"],
                    "evidence_summary": "Model v2 caused 6% drop",
                })
            return "{}"

        return mock_llm

    def _make_test_rows(self):
        """Create minimal metric rows for pipeline execution."""
        return [
            {
                "period": "current",
                "click_quality_value": 0.25,
                "ai_trigger": 0.4,
                "ai_success": 0.6,
            },
            {
                "period": "baseline",
                "click_quality_value": 0.31,
                "ai_trigger": 0.4,
                "ai_success": 0.6,
            },
        ]

    def test_full_pipeline_produces_complete_trace_tree(self):
        """Full pipeline run should produce stage + guardrail spans.

        WHY: This is the ultimate integration test — does the entire
        chain work together? Stage spans, dual_emit, guardrail spans,
        and flush all exercised in one pipeline run.
        """
        from harness.phoenix_tracer import PHOENIX_AVAILABLE

        if not PHOENIX_AVAILABLE:
            pytest.skip("OTel deps not installed")

        from harness.orchestrator import SearchMetricOrchestrator

        provider, exporter = self._setup_in_memory_provider()

        orch = SearchMetricOrchestrator(llm_callable=self._make_mock_llm())
        result = orch.run(
            question="Click Quality dropped 6.2% WoW",
            rows=self._make_test_rows(),
            metric_field="click_quality_value",
            dimensions=["period"],
        )

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        # Should have stage spans
        assert any("UNDERSTAND" in n for n in span_names), (
            f"Missing UNDERSTAND span. Got: {span_names}"
        )

        # Should have guardrail spans (from seam validations)
        guardrail_spans = [n for n in span_names if "guardrail" in n.lower()]
        assert len(guardrail_spans) >= 1, (
            f"Expected at least 1 guardrail span. Got: {span_names}"
        )

        # InvestigationTrace should also be populated
        trace_data = result.get("trace", {})
        assert len(trace_data.get("spans", [])) >= 1
        assert len(trace_data.get("seam_validations", [])) >= 1

    def test_full_pipeline_with_phoenix_disabled(self):
        """Pipeline works correctly with PHOENIX_AVAILABLE=False (R5).

        WHY: This simulates running in an environment without Phoenix deps.
        All existing functionality must work — zero crashes, zero errors,
        InvestigationTrace fully populated, report structure identical.
        """
        from harness.orchestrator import SearchMetricOrchestrator
        from harness import phoenix_tracer as pt

        with patch.object(pt, "PHOENIX_AVAILABLE", False):
            orch = SearchMetricOrchestrator(
                llm_callable=self._make_mock_llm()
            )
            result = orch.run(
                question="Click Quality dropped 6.2% WoW",
                rows=self._make_test_rows(),
                metric_field="click_quality_value",
                dimensions=["period"],
            )

        # Pipeline should still produce a valid result
        assert result["status"] in ("complete", "blocked")

        # InvestigationTrace should be fully populated
        trace_data = result.get("trace", {})
        assert "trace_id" in trace_data
        assert "spans" in trace_data
        assert "seam_validations" in trace_data
