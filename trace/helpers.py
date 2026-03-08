"""Convenience helpers for trace emission in core tools.

These helpers reduce boilerplate when instrumenting deterministic tools.
Each core tool function accepts an optional trace parameter and calls
emit_deterministic_span() at key decision points.
"""

from typing import Any, Dict, Optional


def emit_deterministic_span(
    trace: Optional[Any],
    tool: str,
    decision: str,
    value: Any,
    human_summary: str,
    agent_context: str,
    stage: str = "UNDERSTAND",
    inputs: Optional[Dict[str, Any]] = None,
    outputs: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a deterministic trace span if trace is provided.

    This is the standard way core tools record decisions. All core tool
    decisions are deterministic (code_enforced=True, swimlane="deterministic").

    Why a helper instead of calling trace.emit() directly?
    1. Core tools shouldn't need to know TraceSpan's field names
    2. swimlane="deterministic" and code_enforced=True are always the same
    3. The None guard means callers don't need if-trace-is-not-None blocks

    Args:
        trace: InvestigationTrace instance, or None to skip emission.
        tool: Fully-qualified tool name (e.g., "core.anomaly.check_data_quality").
        decision: What was decided (e.g., "data_quality_status").
        value: The decision value (e.g., "pass").
        human_summary: One-line summary for DS reviewing trace.
        agent_context: Structured context for downstream agent reasoning.
        stage: Pipeline stage (default "UNDERSTAND" — most core tools serve this stage).
        inputs: Key input data (not full payloads — keep concise).
        outputs: Key output data (not full payloads — keep concise).
    """
    # No-op when trace is None — allows core tools to call unconditionally
    # without wrapping every emit in an if-guard
    if trace is None:
        return

    # Lazy import to avoid coupling core/ -> trace/ at module level.
    # Core tools import helpers.py, so we import TraceSpan here to keep
    # the dependency graph clean and avoid circular imports.
    from trace.span import TraceSpan

    span: TraceSpan = {
        "stage": stage,
        "swimlane": "deterministic",
        "tool": tool,
        "decision": decision,
        "code_enforced": True,
        "value": value,
        "human_summary": human_summary,
        "agent_context": agent_context,
    }

    # Only include inputs/outputs when provided — keeps spans lean
    # by default, only adding data fields when the caller has something
    # meaningful to record
    if inputs is not None:
        span["inputs"] = inputs
    if outputs is not None:
        span["outputs"] = outputs

    trace.emit(span)
