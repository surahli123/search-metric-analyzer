"""Question parser — classifies free-text questions into structured briefs.

WHY THIS EXISTS:
The existing pipeline treats all questions identically — a simple lookup
("what's the CQ formula?") gets the same 4-stage treatment as a complex
investigation ("Click Quality dropped 6.2% overnight across enterprise tenants").
The question parser is the first step toward routing by complexity.

DESIGN DECISION: Rule-based, not LLM-assisted.
This runs BEFORE any LLM call. It needs to be:
1. Deterministic — same question always produces same classification
2. Fast — no API calls, no latency
3. Testable — pure functions with known inputs/outputs

The keyword patterns are tuned for Enterprise Search domain vocabulary.
If a question doesn't match any pattern, it falls back to "adhoc" (simplest mode).

ANALOGY: This is like the query understanding (QU) layer in search —
it classifies intent and extracts entities before the retrieval pipeline runs.
"""

import re
from typing import Any, Dict, List, Optional

from trace.helpers import emit_deterministic_span


# =============================================================================
# Known metric names for extraction
# =============================================================================

# Maps common variations → canonical metric name
# This lets users say "CQ", "click quality", or "click_quality" and get matched
METRIC_ALIASES: Dict[str, str] = {
    # Click Quality
    "click_quality": "click_quality",
    "click quality": "click_quality",
    "cq": "click_quality",
    "dlctr": "click_quality",           # Legacy name (v1.4 rename)
    # Search Quality Success
    "search_quality_success": "search_quality_success",
    "search quality success": "search_quality_success",
    "sqs": "search_quality_success",
    "qsr": "search_quality_success",    # Legacy name
    # AI Trigger
    "ai_trigger": "ai_trigger",
    "ai trigger": "ai_trigger",
    "sain_trigger": "ai_trigger",       # Legacy name
    # AI Success
    "ai_success": "ai_success",
    "ai success": "ai_success",
    "sain_success": "ai_success",       # Legacy name
    # Zero Result Rate
    "zero_result_rate": "zero_result_rate",
    "zero result rate": "zero_result_rate",
    "zrr": "zero_result_rate",
    # Latency
    "latency": "latency",
    "p50": "latency",
    "p99": "latency",
}

# Sorted by length descending so longer phrases match first
# (e.g., "search quality success" before "search")
_SORTED_ALIASES = sorted(METRIC_ALIASES.keys(), key=len, reverse=True)


# =============================================================================
# Classification patterns — maps keywords to question types
# =============================================================================

# Each pattern has: keywords (any match triggers), and a priority (lower = checked first).
# If multiple patterns match, the one with the most keyword hits wins.
# Ties broken by priority.
CLASSIFICATION_PATTERNS: List[Dict[str, Any]] = [
    {
        "type": "adhoc",
        "priority": 6,
        "keywords": [
            "formula", "what is", "what's", "definition", "how is.*calculated",
            "what tables", "where can i find", "explain",
        ],
    },
    {
        "type": "sev",
        "priority": 1,
        "keywords": [
            "dropped", "spiked", "overnight", "P0", "P1", "crashed",
            "regression", "degraded", "incident", "alert", "broken",
            "went down", "fell", "plummeted",
        ],
    },
    {
        "type": "experiment",
        "priority": 2,
        "keywords": [
            "experiment", "ramp", "A/B test", "ab test", "variant",
            "control", "treatment", "significance", "SRM",
        ],
    },
    {
        "type": "trend",
        "priority": 3,
        "keywords": [
            "trend", "over time", "quarter", "monthly", "weekly",
            "trajectory", "improving", "worsening", "historical",
        ],
    },
    {
        "type": "system_understanding",
        "priority": 5,
        "keywords": [
            "relationship", "how does.*affect", "correlation",
            "impact of", "what drives", "connected to",
        ],
    },
    {
        "type": "deep_dive",
        "priority": 4,
        "keywords": [
            "investigate", "root cause", "deep dive", "analyze",
            "why did", "what caused", "diagnose",
        ],
    },
]


# =============================================================================
# Time range extraction patterns
# =============================================================================

TIME_PATTERNS: Dict[str, List[str]] = {
    "wow": ["wow", "week over week", "week-over-week", "last week", "this week", "weekly"],
    "mom": ["mom", "month over month", "month-over-month", "last month", "monthly"],
    "qoq": ["qoq", "quarter over quarter", "last quarter", "quarterly"],
    "custom": [],  # Custom dates detected by regex below
}

# ISO date pattern for explicit date ranges
DATE_REGEX = re.compile(r"\d{4}-\d{2}-\d{2}")


# =============================================================================
# Investigation plan templates
# =============================================================================

# Ordered investigation steps by question type.
# These guide the pipeline on what to check and in what order.
INVESTIGATION_PLANS: Dict[str, List[str]] = {
    "sev": [
        "Check data quality and freshness",
        "Run decomposition by all dimensions",
        "Detect step change timing",
        "Match co-movement pattern",
        "Generate hypotheses ordered by priority",
        "Investigate top hypotheses in parallel",
        "Synthesize findings into incident report",
    ],
    "experiment": [
        "Check data quality and freshness",
        "Validate experiment arm ratios (SRM check)",
        "Run decomposition by experiment arms",
        "Compare treatment vs control metrics",
        "Check for interaction effects with other experiments",
        "Synthesize experiment evaluation",
    ],
    "trend": [
        "Check data quality across full time range",
        "Run decomposition for each time period",
        "Detect trend direction and inflection points",
        "Correlate with known events (deployments, seasonality)",
        "Synthesize trend analysis",
    ],
    "deep_dive": [
        "Check data quality and freshness",
        "Run decomposition by all dimensions",
        "Detect step change timing",
        "Match co-movement pattern",
        "Generate hypotheses with broad coverage",
        "Investigate all hypotheses (not just top N)",
        "Cross-validate findings across hypotheses",
        "Synthesize comprehensive analysis",
    ],
    "system_understanding": [
        "Identify the metrics and components involved",
        "Load relevant pipeline knowledge",
        "Map causal chains between components",
        "Synthesize explanation with domain context",
    ],
    "adhoc": [
        "Route to knowledge lookup",
        "Return direct answer from knowledge base",
    ],
}


# =============================================================================
# Core parser functions
# =============================================================================

def extract_metric_hints(question: str) -> List[str]:
    """Extract metric names from a free-text question.

    Scans the question for known metric names and aliases, returning
    canonical metric names. Handles case-insensitive matching and
    common abbreviations (CQ, SQS, ZRR).

    Args:
        question: The raw question text.

    Returns:
        Deduplicated list of canonical metric names found in the question.
        Order matches first appearance in the question text.
    """
    lower_q = question.lower()
    found = []
    seen = set()

    # Check aliases from longest to shortest (avoids partial matches)
    for alias in _SORTED_ALIASES:
        if alias in lower_q:
            canonical = METRIC_ALIASES[alias]
            if canonical not in seen:
                found.append(canonical)
                seen.add(canonical)

    return found


def extract_time_range(question: str) -> Dict[str, Any]:
    """Extract time range hints from a question.

    Looks for standard comparison patterns (WoW, MoM) and explicit dates.

    Args:
        question: The raw question text.

    Returns:
        Dict with "type" key and optional date fields.
        Defaults to {"type": "wow"} when no time signal is found
        (WoW is the most common comparison in Enterprise Search).
    """
    lower_q = question.lower()

    # Check named patterns first (WoW, MoM, QoQ)
    for period_type, patterns in TIME_PATTERNS.items():
        if period_type == "custom":
            continue  # Handle custom dates separately
        for pattern in patterns:
            if pattern in lower_q:
                return {"type": period_type}

    # Check for explicit dates
    dates = DATE_REGEX.findall(question)
    if len(dates) >= 2:
        return {"type": "custom", "start": dates[0], "end": dates[1]}
    elif len(dates) == 1:
        return {"type": "custom", "start": dates[0]}

    # Default to WoW — the most common comparison period
    return {"type": "wow"}


def classify_question_type(question: str) -> tuple:
    """Classify a question into one of 6 types using keyword matching.

    Returns both the type and the matching signals (for explainability).
    If multiple types match, the one with the most keyword hits wins.
    Ties are broken by priority (lower = higher priority).

    Args:
        question: The raw question text.

    Returns:
        Tuple of (question_type, matched_keywords) where matched_keywords
        is a list of the keywords that triggered this classification.
    """
    lower_q = question.lower()
    best_type = "adhoc"  # Default fallback
    best_score = 0
    best_priority = 999
    best_matches = []

    for pattern in CLASSIFICATION_PATTERNS:
        matches = []
        for kw in pattern["keywords"]:
            # Use regex for patterns with wildcards, plain search otherwise
            if ".*" in kw:
                if re.search(kw, lower_q):
                    matches.append(kw)
            elif kw.lower() in lower_q:
                matches.append(kw)

        score = len(matches)
        priority = pattern["priority"]

        # Only consider patterns that actually matched at least one keyword.
        # Without this guard, an empty question would pick whichever pattern
        # has the lowest priority number (sev) instead of defaulting to adhoc.
        if score == 0:
            continue

        # More matches wins; ties broken by priority (lower = better)
        if score > best_score or (score == best_score and priority < best_priority):
            best_type = pattern["type"]
            best_score = score
            best_priority = priority
            best_matches = matches

    return best_type, best_matches


def build_complexity_signals(
    question_type: str,
    metric_hints: List[str],
    question: str,
) -> List[str]:
    """Build explainable complexity signals for mode selection.

    These signals explain WHY the question has its complexity level,
    making mode selection transparent and debuggable.

    Args:
        question_type: The classified question type.
        metric_hints: Extracted metric names.
        question: The raw question text for additional signal extraction.

    Returns:
        List of human-readable complexity signals.
    """
    signals = []
    lower_q = question.lower()

    # Multiple metrics → higher complexity
    if len(metric_hints) > 1:
        signals.append(f"multiple_metrics ({len(metric_hints)} found)")

    # Severity indicators → higher complexity
    if any(sev in lower_q for sev in ["p0", "critical", "incident"]):
        signals.append("P0_severity")
    elif any(sev in lower_q for sev in ["p1", "significant"]):
        signals.append("P1_severity")

    # Cross-metric analysis → higher complexity
    if any(phrase in lower_q for phrase in ["relationship", "correlation", "impact of"]):
        signals.append("cross_metric_analysis")

    # Question type contributes to complexity
    type_complexity = {
        "adhoc": "simple_lookup",
        "sev": "diagnostic",
        "experiment": "evaluation",
        "trend": "longitudinal",
        "deep_dive": "comprehensive",
        "system_understanding": "analytical",
    }
    signals.append(type_complexity.get(question_type, "unknown"))

    return signals


# =============================================================================
# Main entry point
# =============================================================================

def parse_question(
    question: str,
    trace=None,
) -> Dict[str, Any]:
    """Parse a free-text question into a structured QuestionBrief.

    This is the main entry point. It:
    1. Classifies the question type (sev, experiment, trend, etc.)
    2. Extracts metric names from the text
    3. Extracts time range signals
    4. Builds complexity signals for mode selection
    5. Selects an investigation plan template
    6. Emits a trace span recording the classification decision

    Args:
        question: The user's free-text question.
        trace: Optional InvestigationTrace for recording the decision.

    Returns:
        QuestionBrief dict conforming to contracts/question_brief.py.
    """
    # --- Step 1: Classify the question type ---
    question_type, matched_keywords = classify_question_type(question)

    # --- Step 2: Extract metric names ---
    metric_hints = extract_metric_hints(question)

    # --- Step 3: Extract time range ---
    time_range_hints = extract_time_range(question)

    # --- Step 4: Build complexity signals ---
    complexity_signals = build_complexity_signals(question_type, metric_hints, question)

    # --- Step 5: Select investigation plan ---
    investigation_plan = INVESTIGATION_PLANS.get(question_type, INVESTIGATION_PLANS["adhoc"])

    # --- Step 6: Build the QuestionBrief ---
    brief = {
        "raw_question": question,
        "question_type": question_type,
        "metric_hints": metric_hints,
        "time_range_hints": time_range_hints,
        "complexity_signals": complexity_signals,
        "investigation_plan": investigation_plan,
    }

    # --- Step 7: Emit trace span ---
    emit_deterministic_span(
        trace,
        tool="harness.question_parser.parse_question",
        decision="question_classification",
        value=question_type,
        stage="QUESTION_PARSE",
        human_summary=(
            f"Question classified as '{question_type}' "
            f"(metrics: {', '.join(metric_hints) if metric_hints else 'none'}, "
            f"matched: {', '.join(matched_keywords[:3]) if matched_keywords else 'default'})"
        ),
        agent_context=(
            f"question_type={question_type}, "
            f"metric_hints={metric_hints}, "
            f"time_range={time_range_hints.get('type', 'wow')}, "
            f"complexity_signals={complexity_signals}"
        ),
    )

    return brief
