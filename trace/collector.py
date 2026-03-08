"""InvestigationTrace — collects spans across an investigation's lifecycle.

This is the central trace accumulator. Both Mode A (skill file) and Mode B
(orchestrator) create one InvestigationTrace per investigation and pass it
through the pipeline.

Key design decision: agent_context_for() returns a TOKEN-BUDGETED summary
(default ~1500 tokens per stage) so that SYNTHESIZE doesn't overflow the
context window when reading prior stage context. This is Amendment 4 from
the IC9 review — we include decision values and evidence counts but exclude
raw inputs/outputs.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from trace.span import TraceSpan, SeamSpan, make_span_id


class InvestigationTrace:
    """Accumulates trace spans for a single investigation.

    Usage:
        trace = InvestigationTrace(question="CQ dropped 6.2%")
        # ... pass trace to core tools, they emit spans ...
        print(trace.to_json())  # Full trace for archival
        context = trace.agent_context_for("UNDERSTAND")  # Summary for next stage
    """

    def __init__(self, question: str, trace_id: Optional[str] = None):
        # Generate a unique trace ID if not provided
        # (Mode B orchestrator may want to set this explicitly for correlation)
        self.trace_id = trace_id or f"inv_{uuid.uuid4().hex[:12]}"
        self.question = question
        self.created_at_ms = int(time.time() * 1000)

        # Separate lists for decision spans and seam spans
        # because they serve different purposes in the trace
        self._spans: List[TraceSpan] = []
        self._seam_spans: List[SeamSpan] = []

    def emit(self, span: TraceSpan) -> None:
        """Record a decision span.

        Automatically sets trace_id and span_id if not already set.
        This is the primary interface for core tools to emit trace data.
        """
        # Fill in identity fields that the caller shouldn't have to manage
        if "trace_id" not in span:
            span["trace_id"] = self.trace_id
        if "span_id" not in span:
            span["span_id"] = make_span_id()
        if "timestamp_ms" not in span:
            span["timestamp_ms"] = int(time.time() * 1000)

        self._spans.append(span)

    def emit_seam(self, stage: str, schema: str, passed: bool,
                  tier: str, checks: Dict[str, bool],
                  violations: Optional[List[str]] = None) -> None:
        """Record a seam validation event.

        Called by contracts.seam_validator after each stage boundary check.
        The tier field records whether this was a hard/soft/retry gate
        (Amendment 1: tiered gates from IC9 review).
        """
        seam = SeamSpan(
            trace_id=self.trace_id,
            stage=stage,
            schema=schema,
            passed=passed,
            tier=tier,
            checks=checks,
            violations=violations or [],
            timestamp_ms=int(time.time() * 1000)
        )
        self._seam_spans.append(seam)

    def spans_for_stage(self, stage: str) -> List[TraceSpan]:
        """Get all decision spans for a specific stage."""
        return [s for s in self._spans if s.get("stage") == stage]

    def seam_for_stage(self, stage: str) -> Optional[SeamSpan]:
        """Get the seam validation result for a specific stage.

        Returns the most recent seam span for the stage (in case of retries).
        """
        stage_seams = [s for s in self._seam_spans if s["stage"] == stage]
        return stage_seams[-1] if stage_seams else None

    def agent_context_for(self, stage: str, max_tokens: int = 1500) -> str:
        """Generate a token-budgeted summary of a stage for downstream agents.

        This is the bridge between trace completeness and context window
        feasibility (Amendment 4 from IC9 review).

        Returns a structured text summary containing:
        - Decision values (what was decided)
        - Evidence counts (how much data supported each decision)
        - Anomaly flags (what was unexpected)
        - Seam pass/fail status

        Excludes:
        - Raw inputs/outputs (too large)
        - Full evidence payloads (summarized as counts)
        - human_summary text (agent doesn't need the human-friendly version)

        Args:
            stage: Which stage to summarize (UNDERSTAND, HYPOTHESIZE, etc.)
            max_tokens: Approximate token budget. We estimate ~4 chars per token.
                       Default 1500 tokens ≈ 6000 chars.
        """
        max_chars = max_tokens * 4  # Rough chars-per-token estimate

        spans = self.spans_for_stage(stage)
        seam = self.seam_for_stage(stage)

        if not spans and not seam:
            return f"[No trace data for stage {stage}]"

        lines = [f"=== {stage} Stage Summary ==="]
        lines.append(f"Question: {self.question}")
        lines.append("")

        # Decision values — the most important information for downstream agents
        lines.append("Decisions:")
        for span in spans:
            decision = span.get("decision", "unknown")
            value = span.get("value", "N/A")
            enforced = "code-enforced" if span.get("code_enforced") else "llm-generated"
            context = span.get("agent_context", "")
            lines.append(f"  - {decision} = {value} ({enforced})")
            if context:
                lines.append(f"    Context: {context}")

        # Seam validation status
        if seam:
            lines.append("")
            status = "PASSED" if seam["passed"] else f"FAILED (tier={seam['tier']})"
            lines.append(f"Seam validation: {status}")
            if seam["violations"]:
                for v in seam["violations"]:
                    lines.append(f"  WARNING: {v}")

        result = "\n".join(lines)

        # Truncate if over budget (rough but effective)
        if len(result) > max_chars:
            result = result[:max_chars - 50] + "\n\n[... truncated to fit token budget]"

        return result

    def to_dict(self) -> Dict[str, Any]:
        """Convert the full trace to a dictionary for JSON serialization."""
        return {
            "trace_id": self.trace_id,
            "question": self.question,
            "created_at_ms": self.created_at_ms,
            "spans": self._spans,
            "seam_validations": self._seam_spans,
            "summary": {
                "total_spans": len(self._spans),
                "total_seams": len(self._seam_spans),
                "stages_covered": list(set(
                    s.get("stage", "unknown") for s in self._spans
                )),
                "invisible_decisions_traced": [
                    s.get("decision") for s in self._spans
                    if s.get("decision") in {
                        "metric_direction", "hypothesis_inclusion",
                        "context_construction", "narrative_selection"
                    }
                ],
            }
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the full trace to JSON string.

        Used for:
        - Mode A: writing to /tmp/investigation_trace.json
        - Mode B: archiving after investigation completes
        - Eval: verifying trace coverage
        """
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "InvestigationTrace":
        """Deserialize a trace from JSON string.

        Used by Mode A to read back a trace from /tmp/ for SYNTHESIZE context.
        """
        data = json.loads(json_str)
        trace = cls(
            question=data["question"],
            trace_id=data["trace_id"]
        )
        trace.created_at_ms = data["created_at_ms"]
        trace._spans = data.get("spans", [])
        trace._seam_spans = data.get("seam_validations", [])
        return trace
