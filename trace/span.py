"""TraceSpan — the atomic unit of investigation tracing.

Each span captures a single decision point in the investigation pipeline.
Spans have two audiences:
- human_summary: A plain-English explanation for a DS reviewing the trace
- agent_context: A structured summary for downstream agents to reason about

Design rationale: We use TypedDict (not dataclass) to match the contracts module
and to allow easy JSON serialization without custom encoders.
"""

import time
import uuid
from typing import Any, Dict, List, Optional, TypedDict


class TraceSpan(TypedDict, total=False):
    """A single traced decision in the investigation pipeline.

    Fields marked total=False are optional — not every span needs every field.
    Required fields (set by emit()): trace_id, stage, swimlane, tool, timestamp_ms.
    """
    # Identity
    trace_id: str                   # UUID for the investigation
    span_id: str                    # UUID for this specific span

    # Classification
    stage: str                      # UNDERSTAND | HYPOTHESIZE | DISPATCH | SYNTHESIZE
    swimlane: str                   # deterministic | llm_generated | hybrid
    tool: str                       # e.g. "core.anomaly.check_data_quality"

    # Decision tracking (maps to IC9 Invisible Decisions)
    decision: str                   # e.g. "metric_direction", "hypothesis_inclusion"
    code_enforced: bool             # True = Python gate; False = LLM/prompt
    value: Any                      # The key decision value
    alternatives_considered: List[Dict[str, Any]]  # For deterministic spans
    constrained_by: List[str]       # For LLM spans — what rules bounded the output

    # Data
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]

    # Dual-audience summaries
    human_summary: str              # For DS reviewing the trace
    agent_context: str              # For downstream agent reasoning

    # Timing
    timestamp_ms: int
    duration_ms: int


class SeamSpan(TypedDict):
    """A seam validation event — emitted when a stage boundary is checked.

    Seam spans are distinct from decision spans: they record whether
    the contract between stages was satisfied, not what decision was made.
    """
    trace_id: str
    stage: str                      # Which stage's output was validated
    schema: str                     # e.g. "UnderstandResult"
    passed: bool
    tier: str                       # "hard" | "soft" | "retry" — from tiered gates
    checks: Dict[str, bool]         # Individual rule results
    violations: List[str]           # Human-readable violation messages
    timestamp_ms: int


def make_span_id() -> str:
    """Generate a unique span ID using timestamp + random suffix.

    We use this instead of uuid4() to keep spans roughly sortable by time,
    which helps when reading traces chronologically.
    """
    return f"span_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
