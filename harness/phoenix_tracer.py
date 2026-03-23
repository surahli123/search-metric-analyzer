"""Phoenix/OTel observability layer for the investigation pipeline.

This module adds Arize Phoenix tracing as a COMPLEMENT to the existing
trace/ enforcement system. It emits OpenTelemetry spans alongside
InvestigationTrace spans, giving visibility into LLM calls, token costs,
and latency — things the enforcement trace doesn't capture.

ARCHITECTURE:
- Lives in harness/ (Layer 4), NOT trace/ (Layer 3)
- All functions no-op gracefully when OTel deps aren't installed
- Single PHOENIX_AVAILABLE flag guards all OTel code paths
- register_phoenix() is idempotent — safe to call on every pipeline run

DEPENDENCY BUDGET:
- arize-phoenix-otel: thin OTel wrapper
- openinference-instrumentation-anthropic: Anthropic SDK auto-patcher
- opentelemetry-sdk: standard OTel (explicit for InMemorySpanExporter in tests)
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# --- Import guard: OTel deps are optional dev-time dependencies ---
# WHY try/except instead of importlib: simpler, standard pattern, and
# we need the actual objects (TracerProvider, etc.) at module level
# for type hints and function bodies.
try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        SpanExporter,
    )
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )
    from openinference.instrumentation.anthropic import (
        AnthropicInstrumentor,
    )

    PHOENIX_AVAILABLE = True
except ImportError:
    PHOENIX_AVAILABLE = False


# --- Module-level state for idempotency (R1) ---
# WHY module-level: register_phoenix() is called at the start of every
# pipeline run. Without this guard, we'd create duplicate TracerProviders
# and AnthropicInstrumentor would monkey-patch the SDK multiple times,
# which can cause duplicate LLM spans.
_tracer_provider: Optional[Any] = None


def register_phoenix(
    endpoint: str = "http://localhost:6006/v1/traces",
    project_name: str = "search-metric-analyzer",
) -> Optional[Any]:
    """Initialize OTel TracerProvider + Anthropic auto-instrumentation.

    Idempotent: if already registered, returns the existing provider.
    No-ops when PHOENIX_AVAILABLE is False (returns None).

    Args:
        endpoint: Phoenix server OTLP endpoint. Default is local sidecar.
        project_name: Project name shown in Phoenix UI.

    Returns:
        TracerProvider if successful, None if Phoenix deps not installed.
    """
    global _tracer_provider

    # No-op when deps aren't installed — graceful degradation
    if not PHOENIX_AVAILABLE:
        return None

    # Idempotency guard (R1): return existing provider if already set up
    if _tracer_provider is not None:
        return _tracer_provider

    # Create TracerProvider with batch exporter pointing at Phoenix
    # WHY BatchSpanProcessor: buffers spans and sends in batches,
    # reducing overhead during pipeline execution. We flush explicitly
    # at pipeline end (see flush() below).
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))

    # Register as the global tracer provider so auto-instrumentation
    # and stage_span() both use the same provider
    otel_trace.set_tracer_provider(provider)

    # Auto-instrument Anthropic SDK (R4)
    # WHY explicit call: the instrumentor monkey-patches
    # anthropic.Client.messages.create() to emit LLM spans automatically.
    # These spans nest inside our CHAIN stage spans, giving a complete
    # picture of what happened inside each pipeline stage.
    # WHY broad except: observability must NEVER block the pipeline.
    # A version mismatch or API change in the instrumentor should degrade
    # gracefully, not crash the investigation.
    try:
        AnthropicInstrumentor().instrument(tracer_provider=provider)
    except Exception:
        logger.warning("Anthropic auto-instrumentation failed — skipping")

    # Auto-instrument OpenAI SDK
    # WHY: without this, OpenAI-compatible API calls (Novita, Together, Groq)
    # are invisible in Phoenix traces. Same guard pattern as Anthropic.
    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor
        OpenAIInstrumentor().instrument(tracer_provider=provider)
    except Exception:
        # ImportError = package not installed (fine — skip silently)
        # Other exceptions = version mismatch, API change (warn and continue)
        logger.warning("OpenAI auto-instrumentation failed or not installed — skipping")

    _tracer_provider = provider
    logger.info(
        "Phoenix tracer registered: endpoint=%s, project=%s",
        endpoint,
        project_name,
    )
    return _tracer_provider


# --- Tracer name used for all spans created by this module ---
_TRACER_NAME = "search-metric-analyzer"


@contextmanager
def stage_span(stage: str, mode: str = "medium"):
    """Context manager that wraps a pipeline stage in an OTel CHAIN span.

    Usage in orchestrator._run_pipeline():
        with stage_span("UNDERSTAND", mode="medium"):
            result = stage_understand(...)

    The span captures:
    - sma.stage: stage name (UNDERSTAND, HYPOTHESIZE, etc.)
    - sma.mode: execution mode (simple, medium, complex)
    - Duration: automatic via context manager
    - Exceptions: OTel records them if raised within the with-block

    Auto-instrumented LLM calls (via AnthropicInstrumentor) nest inside
    the stage span as child spans, creating a hierarchical trace tree.

    Args:
        stage: Pipeline stage name (e.g., "UNDERSTAND").
        mode: Execution mode (e.g., "medium", "complex").

    Yields:
        The OTel span if Phoenix is available, None otherwise.
    """
    # No-op when Phoenix deps aren't installed
    if not PHOENIX_AVAILABLE:
        yield None
        return

    # Guard OTel setup separately from the body. If we wrapped the yield
    # in a try/except, body exceptions (StageError, LLMParseError) would
    # be caught and swallowed — breaking the pipeline's error handling.
    try:
        tracer = otel_trace.get_tracer(_TRACER_NAME)
    except Exception:
        # Critical gap #1: OTel errors must never crash the pipeline.
        logger.warning(
            "stage_span(%s) failed during setup — OTel error suppressed",
            stage, exc_info=True,
        )
        yield None
        return

    # Use start_as_current_span as a context manager — body exceptions
    # propagate naturally (OTel records them on the span automatically).
    with tracer.start_as_current_span(stage) as span:
        try:
            span.set_attribute("sma.stage", stage)
            span.set_attribute("sma.mode", mode)
        except Exception:
            # Attribute-setting errors are ignorable — the span still works
            logger.warning(
                "stage_span(%s) attribute error suppressed", stage,
                exc_info=True,
            )
        yield span


def dual_emit(
    trace: Optional[Any],
    tool: str,
    decision: str,
    value: Any,
    human_summary: str,
    agent_context: str,
    stage: str = "UNDERSTAND",
    swimlane: str = "deterministic",
    inputs: Optional[Dict[str, Any]] = None,
    outputs: Optional[Dict[str, Any]] = None,
    constrained_by: Optional[List[str]] = None,
) -> None:
    """Emit a span to BOTH InvestigationTrace and OTel (if available).

    This is the unified replacement for emit_deterministic_span() and
    direct trace.emit(TraceSpan(...)) calls. It writes to the enforcement
    trace unconditionally and adds OTel attributes when Phoenix is active.

    The swimlane parameter (R2) determines code_enforced:
    - "deterministic" → code_enforced=True (UNDERSTAND stage, core tools)
    - "llm_generated" → code_enforced=False (HYPOTHESIZE/DISPATCH/SYNTHESIZE)

    Args:
        trace: InvestigationTrace instance, or None to skip emission entirely.
        tool: Fully-qualified tool name.
        decision: What was decided.
        value: The decision value.
        human_summary: One-line summary for DS reviewing trace.
        agent_context: Structured context for downstream agent reasoning.
        stage: Pipeline stage (default "UNDERSTAND").
        swimlane: "deterministic" or "llm_generated" (default "deterministic").
        inputs: Optional key input data.
        outputs: Optional key output data.
        constrained_by: Optional list of business rule names that bounded the output
            (used for LLM-generated spans to record what rules the LLM was given).
    """
    # No-op when trace is None — same pattern as emit_deterministic_span()
    if trace is None:
        return

    # --- Side 1: Write to InvestigationTrace (enforcement layer) ---
    # Lazy import to match the pattern in trace/helpers.py
    from trace.span import TraceSpan

    code_enforced = swimlane == "deterministic"

    span: TraceSpan = {
        "stage": stage,
        "swimlane": swimlane,
        "tool": tool,
        "decision": decision,
        "code_enforced": code_enforced,
        "value": value,
        "human_summary": human_summary,
        "agent_context": agent_context,
    }

    if inputs is not None:
        span["inputs"] = inputs
    if outputs is not None:
        span["outputs"] = outputs
    if constrained_by is not None:
        span["constrained_by"] = constrained_by

    trace.emit(span)

    # --- Side 2: Write to OTel as attributes on current span ---
    # WHY attributes on current span (not a new child span): the decision
    # is metadata about the stage, not a separate operation. Phoenix shows
    # these as properties on the stage span in the UI.
    if not PHOENIX_AVAILABLE:
        return

    try:
        current_span = otel_trace.get_current_span()
        if current_span and current_span.is_recording():
            current_span.set_attribute("sma.decision", decision)
            current_span.set_attribute("sma.decision.value", str(value))
            current_span.set_attribute("sma.decision.tool", tool)
            current_span.set_attribute("sma.swimlane", swimlane)
            current_span.set_attribute("sma.code_enforced", code_enforced)
            current_span.set_attribute("sma.human_summary", human_summary)
    except Exception:
        # OTel errors must never crash the pipeline
        logger.warning(
            "dual_emit OTel write failed for decision=%s", decision,
            exc_info=True,
        )


def emit_guardrail(
    stage: str,
    passed: bool,
    tier: str,
    violations: List[str],
) -> None:
    """Emit a GUARDRAIL span for a seam validation event.

    Called by validate_seam() AFTER the existing trace.emit_seam() call.
    This adds the validation to Phoenix's trace tree so you can see
    which business rules passed/failed at each stage boundary.

    No-ops when Phoenix deps aren't installed.

    Args:
        stage: The pipeline stage that was validated (e.g., "UNDERSTAND").
        passed: Whether all business rules passed.
        tier: Gate tier ("hard", "soft", or "retry").
        violations: List of human-readable violation messages (empty if passed).
    """
    if not PHOENIX_AVAILABLE:
        return

    try:
        tracer = otel_trace.get_tracer(_TRACER_NAME)
        with tracer.start_as_current_span(f"guardrail:{stage}") as span:
            span.set_attribute("sma.guardrail.stage", stage)
            span.set_attribute("sma.guardrail.passed", passed)
            span.set_attribute("sma.guardrail.tier", tier)
            span.set_attribute(
                "sma.guardrail.violations",
                "; ".join(violations) if violations else "",
            )
    except Exception:
        logger.warning(
            "emit_guardrail(%s) failed — OTel error suppressed", stage,
            exc_info=True,
        )


def flush(provider: Optional[Any], timeout_ms: int = 5000) -> None:
    """Force-flush the OTel batch exporter.

    Called at the end of _run_pipeline() to ensure all spans are sent
    to Phoenix before the process exits. Without this, short investigations
    might finish before the batch exporter triggers.

    Logs a warning if the flush times out (critical gap #2).

    Args:
        provider: TracerProvider returned by register_phoenix(), or None.
        timeout_ms: Maximum time to wait for flush (default 5 seconds).
    """
    if provider is None:
        return

    try:
        success = provider.force_flush(timeout_millis=timeout_ms)
        if not success:
            logger.warning(
                "Phoenix flush timed out after %dms — some spans may be lost",
                timeout_ms,
            )
    except Exception:
        logger.warning(
            "Phoenix flush failed — spans may be lost",
            exc_info=True,
        )
