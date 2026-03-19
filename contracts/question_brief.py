"""QUESTION_PARSE stage contract — output of the question framing phase.

This stage runs BEFORE UNDERSTAND. It parses a free-text question into a
structured brief that mode selection and the pipeline can consume.

Think of it like query understanding in search: the raw query gets classified,
enriched with metadata, and structured before the retrieval pipeline runs.
Without this, the system treats "what's the CQ formula?" the same as
"Click Quality dropped 6.2% overnight across enterprise tenants" — routing
both through the same 4-stage investigation pipeline.

Seam tier: HARD — a bad question brief means wrong mode → wasted work.
"""

from typing import Any, Dict, List, Optional, TypedDict


class QuestionBrief(TypedDict, total=False):
    """Contract for QUESTION_PARSE → MODE_SELECT → UNDERSTAND boundary.

    Seam tier: HARD — invalid briefs halt before the investigation starts.

    Fields:
        raw_question: The user's original question text, preserved verbatim.
        question_type: Classification into one of 6 types that determine
            how the pipeline processes the question.
        metric_hints: Metric names extracted from the question text.
            Required for all non-adhoc types (the pipeline needs to know
            which metrics to analyze).
        time_range_hints: Time range signals extracted from the question.
            wow = week-over-week, mom = month-over-month, custom = explicit dates.
        complexity_signals: Reasons why this question has its complexity level.
            Used by mode selector to explain routing decisions.
        investigation_plan: Ordered list of investigation steps suggested by
            the question type and metrics involved.
    """
    raw_question: str
    question_type: str              # "sev" | "experiment" | "trend" | "deep_dive" | "system_understanding" | "adhoc"
    metric_hints: List[str]         # Extracted metric names (e.g., ["click_quality", "ai_trigger"])
    time_range_hints: Dict[str, Any]  # {"type": "wow"} or {"type": "custom", "start": ..., "end": ...}
    complexity_signals: List[str]   # Why this complexity (e.g., ["multiple_metrics", "P0_severity"])
    investigation_plan: List[str]   # Ordered steps (e.g., ["check decomposition", "run co-movement"])
