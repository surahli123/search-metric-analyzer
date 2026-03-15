"""UNDERSTAND stage contract — output of the data analysis phase.

This stage is mostly deterministic (Python tools). It answers:
"What happened? How big is it? Is the data trustworthy?"

Key IC9 fix: metric_direction is now a REQUIRED field (Invisible Decision #1).
Key Amendment: mix_shift_result is now a first-class field (Amendment 3).
"""

from typing import Any, Dict, List, Optional, TypedDict


class StepChangeResult(TypedDict, total=False):
    """Output of step-change detection from core.anomaly.detect_step_change()."""
    detected: bool
    change_point_week: str       # ISO week where the change occurred
    pre_mean: float
    post_mean: float
    magnitude: float             # Absolute change
    z_score: float               # Statistical significance
    direction: str               # "up" | "down"


class CoMovementResult(TypedDict, total=False):
    """Output of co-movement pattern matching from core.anomaly.match_co_movement_pattern().

    This captures which archetype pattern the metric movements match,
    e.g., "ai_adoption_expected" when AI trigger rises and CQ drops.
    """
    pattern_name: str            # e.g. "ai_adoption_expected", "ranking_regression"
    match_score: float           # 0.0-1.0, threshold >= 0.75
    runner_up: Optional[str]     # Second-best pattern match
    runner_up_score: Optional[float]
    movements: Dict[str, str]    # metric_name → "up" | "down" | "stable"


class MixShiftResult(TypedDict, total=False):
    """Output of mix-shift decomposition from core.decompose.

    Mix-shift causes 30-40% of Enterprise metric movements — it's when the
    composition of traffic changes (e.g., more mobile users) rather than
    the behavior within segments changing. This deserves first-class
    representation in the contract because HYPOTHESIZE needs to know
    whether mix-shift was detected to generate appropriate hypotheses.

    Amendment 3 from IC9 review: "mix-shift is a first-class diagnostic
    pattern but had no first-class contract representation."
    """
    detected: bool                   # True if mix-shift contribution > threshold
    contribution_pct: float          # e.g. 0.35 = "mix-shift explains 35%"
    top_segments: List[Dict[str, Any]]  # Which segments drove it
    behavioral_contribution_pct: float  # How much is behavior change vs. mix


class UnderstandResult(TypedDict, total=False):
    """Contract for UNDERSTAND → HYPOTHESIZE boundary.

    Seam tier: HARD — if this fails, the investigation halts.
    Rationale: Garbage in = garbage out. No point generating hypotheses
    on data that fails quality checks.
    """
    question: str                    # Original user question
    metric: str                      # e.g. "click_quality", "search_quality_success"
    direction: str                   # "up" | "down" | "stable"
    severity: str                    # "P0" | "P1" | "P2" | "normal"
    data_quality_status: str         # "pass" | "warn" | "fail"
    step_change: Optional[StepChangeResult]
    co_movement_pattern: CoMovementResult
    mix_shift_result: Optional[MixShiftResult]   # Amendment 3
    metric_direction: str            # IC9 Invisible Decision #1 — REQUIRED
    data_quality_details: Optional[Dict[str, Any]]  # For degraded report on failure
